#!/usr/bin/env python3

EXTERNAL_IMAGES_ROOT = '/mnt/storage/sondemaps'
EXTERNAL_IMAGES_URL = 'https://sondemaps.lectrobox.com/'

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from geographiclib.geodesic import Geodesic
from pyproj import Transformer
from typing import Tuple
import argparse
import boto3
import contextily as cx  # type: ignore
import geocoder
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import requests
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
import constants
import table_definitions
import util

from boto3.dynamodb.conditions import Attr

matplotlib.use('Agg')

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

# conversion factors
METERS_PER_MILE = 1609.34
METERS_PER_KM   = 1000
METERS_PER_FOOT = 0.3048

# sondehup API
SONDEHUB_DATA_URL = 'https://api.v2.sondehub.org/sondes/telemetry'
MAX_SONDEHUB_RETRIES = 6

# URLs for email body
SONDEHUB_MAP_URL = 'https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f={serial}&q={serial}'
GMAP_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

# Get sonde data from the same live API that the SondeHub web site uses
class SondeHubTelemetryRetriever:
    def __init__(self):
        pass

    def get_sonde_data(self, params):
        response = requests.get(SONDEHUB_DATA_URL, params=params)
        response.raise_for_status()
        return response.json()

    def get_elevation_data(self, lat, lon):
        resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
            'x': lon,
            'y': lat,
            'units': 'Meters',
            'wkid': '4326',
            'includeDate': 'True',
        })
        resp.raise_for_status()
        return resp.json()


class EmailNotifier:
    def __init__(self, args, retriever):
        self.args = args
        self.retriever = retriever
        self.wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
        self.ses_client = boto3.client('ses')

    #
    # Sonde data retrieval
    #

    # Clean up and annotate telemetry returned by sondehub
    def cleanup_sonde_data(self, sondes):
        # Sometimes lat/lon comes as a string instead of float
        sondes = sondes.astype({
            'alt': float,
            'vel_v': float,
            'vel_h': float,
            'lat': float,
            'lon': float,
        })

        sondes['datetime'] = pd.to_datetime(sondes['datetime'])

        return sondes

    def get_sonde_data_once(self, params):
        try:
            response = self.retriever.get_sonde_data(params)
        except Exception as e:
            print(f'Error getting data from sondehub: {e}')
            return None

        def unpack_list():
            for sonde, timeblock in response.items():
                for _, record in timeblock.items():
                    yield record
        sondes = pd.DataFrame(unpack_list())
        sondes = self.cleanup_sonde_data(sondes)
        return sondes

    def get_sonde_data(self, params):
        retries = 0
        while retries <= MAX_SONDEHUB_RETRIES:
            if retries > 0:
                print("Sondehub data failure; retrying after a short sleep...")
                time.sleep((2**retries) * 4)
            retries += 1
            sondes = self.get_sonde_data_once(params)
            if sondes is not None and len(sondes) > 0:
                return sondes
            print('Sondehub returned empty dataframe -- trying again')

        raise Exception(f"Couldn't get sondehub data, even after {MAX_SONDEHUB_RETRIES} retries")

    ### Getting the nearest sonde

    def annotate_with_distance(self, sondes, config):
        def get_path(sonde):
            path = Geodesic.WGS84.Inverse(config['lat'], config['lon'], sonde['lat'], sonde['lon'])
            return (
                path['s12'],
                (path['azi1'] + 360) % 360
            )

        # Annotate all landing records with distance from home
        sondes[['dist_from_home_m', 'bearing_from_home']] = sondes.apply(
            get_path,
            axis=1,
            result_type='expand')

        return sondes

    def get_nearest_landed_sonde(self, sondes, config):
        sondes = self.annotate_with_distance(sondes, config)

        # Find the landing closest to home
        nearest_landing = sondes.loc[sondes['dist_from_home_m'].idxmin()]

        return nearest_landing

    ####
    #### Drawing map
    ####

    def to_mercator_xy(self, lat, lon):
        return self.wgs84_to_mercator.transform(lat, lon)

    MAP_WHITESPACE = 0.2

    def get_map_limits(self, points) -> Tuple[float, float, float, float, float]:
        min_lat = min([point[0] for point in points])
        max_lat = max([point[0] for point in points])
        min_lon = min([point[1] for point in points])
        max_lon = max([point[1] for point in points])
        min_x, min_y = self.to_mercator_xy(min_lat, min_lon)
        max_x, max_y = self.to_mercator_xy(max_lat, max_lon)
        x_pad = (max_x - min_x) * self.MAP_WHITESPACE
        y_pad = (max_y - min_y) * self.MAP_WHITESPACE
        max_pad = max(x_pad, y_pad)
        min_x -= max_pad
        max_x += max_pad
        min_y -= max_pad
        max_y += max_pad

        # Calculate the zoom
        lat_length = max_lat - min_lat
        lon_length = max_lon - min_lon
        zoom_lat = np.ceil(np.log2(360 * 2.0 / lat_length))
        zoom_lon = np.ceil(np.log2(360 * 2.0 / lon_length))
        zoom = np.min([zoom_lon, zoom_lat])
        zoom = int(zoom) + 1

        return min_x, min_y, max_x, max_y, zoom

    def get_email_image(self, config, size, flight, landing):
        fig, ax = plt.subplots(figsize=(size, size))
        ax.axis('off')

        # Plot the balloon's path
        (flight_x, flight_y) = self.to_mercator_xy(flight.lat, flight.lon)
        ax.plot(flight_x, flight_y, color='red')

        # Plot a line from home to the landing point
        home_x, home_y = self.to_mercator_xy(config['lat'], config['lon'])
        sonde_x, sonde_y = self.to_mercator_xy(landing['lat'], landing['lon'])
        ax.plot([home_x, sonde_x], [home_y, sonde_y], color='blue', marker='*')
        ax.annotate(
            xy=[home_x, home_y],
            text='home',
            xytext=[10, 0],
            textcoords='offset points',
            arrowprops=dict(arrowstyle='-'),
        )

        # Plot a line from the last receiver to the landing point
        rx_lat, rx_lon = [float(f) for f in landing['uploader_position'].split(',')]
        rx_x, rx_y = self.to_mercator_xy(rx_lat, rx_lon)
        ax.plot([rx_x, sonde_x], [rx_y, sonde_y], color='springgreen', marker='*')
        ax.annotate(
            xy=[rx_x, rx_y],
            text=f"rx ({landing['uploader_callsign']})",
            xytext=[10, 0],
            textcoords='offset points',
            arrowprops=dict(arrowstyle='-'),
        )

        # Find the limits of the map
        min_x, min_y, max_x, max_y, zoom = self.get_map_limits([
            [config['lat'], config['lon']],
            [landing['lat'], landing['lon']],
            [rx_lat, rx_lon],
        ])
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        print(f"{config['email']}: downloading at zoomlevel {zoom}")

        cx.add_basemap(
            ax,
            zoom=zoom,
            source=cx.providers.OpenStreetMap.Mapnik,
            #source=cx.providers.CyclOSM,
            #source=cx.providers.Stamen.Terrain,
            #source=cx.providers.Stamen.TopOSMFeatures,
        )
        fig.tight_layout()

        return fig

    ####
    #### Sending email
    ####

    def get_elevation(self, lat, lon):
        try:
            resp = self.retriever.get_elevation_data(lat, lon)
            return float(resp['value'])
        except Exception as e:
            print(f'Elevation API gave invalid response: {e}')
            return None

    def render_elevation(self, config, meters):
        if config['units'] == 'imperial':
            feet = meters / METERS_PER_FOOT
            return f"{round(feet):,} ft"
        else:
            return f"{round(meters):,} m"

    def render_distance(self, config, meters):
        if config['units'] == 'imperial':
            miles = meters / METERS_PER_MILE
            return f"{round(miles):,} miles"
        else:
            km = meters / METERS_PER_KM
            return f"{round(km):,} km"

    def get_email_text(self, config, landing):
        # attempt a geocode and DEM lookup
        geo = geocoder.osm(f"{landing['lat']}, {landing['lon']}")
        elev = self.get_elevation(landing['lat'], landing['lon'])

        # sonde still in contact from the ground?
        ground_reception = abs(landing['vel_v']) < 1 and abs(landing['vel_h']) < 1

        place = ""
        if geo and geo.county:
            if geo.town:
                place += geo.town + ", "
            if geo.city:
                place += geo.city + ", "
            place += geo.county

        # get landing time in config-specified timezone
        landing_localtime = landing['datetime'].tz_convert(config['tzname'])

        # subject line
        subj = ""
        if ground_reception:
            subj += 'GROUND RECEPTION! '
        subj += f"{landing_localtime.month_name()} {landing_localtime.day} "
        subj += "morning" if landing_localtime.hour < 12 else "afternoon"
        subj += " sonde landed "
        subj += self.render_distance(config, landing['dist_from_home_m'])
        subj += f" from home, bearing {round(landing.bearing_from_home)}°"
        if place:
            subj += f" ({place})"

        # body
        uploaders = [u['uploader_callsign'] for u in landing['uploaders']]

        body = '''
    <html>
    <head>
    <style>
    table.sonde {
        background-color: #e0e0e0;
    }
    table.sonde th {
        background-color:  #404040;
        color: white;
    }
    table.sonde tbody tr:nth-child(odd) {
        background-color:  #d0d0d0;
    }
    </style>
    </head>
    <body>
        '''

        body += f'''
    <table class="sonde">
        <tr>
            <td>Sonde ID</td>
            <td><a href="{SONDEHUB_MAP_URL.format(serial=landing.serial)}">{landing.serial}</a></td>
        </tr>
        <tr>
            <th colspan="2">Last Reception</td>
        </tr>
        <tr>
            <td>Heard</td>
            <td>{landing_localtime.strftime("%Y-%m-%d %H:%M:%S %Z")} by {", ".join(uploaders)}</td>
        </tr>
        <tr>
            <td>Altitude</td>
            <td>{self.render_elevation(config, landing['alt'])}</td>
        </tr>
        <tr>
            <td>Position</td>
            <td><a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a></td>
        </tr>
        '''

        if place:
            nearest_addr = place
            if geo and geo.address:
                nearest_addr += f'<br>{geo.address}'
            body += f'''
        <tr>
            <td>Address</td>
            <td>{nearest_addr}</td>
        </tr>
            '''

        body += f'''
        <tr>
            <td>Distance</td>
            <td>{self.render_distance(config, landing['dist_from_home_m'])} from home</td>
        </tr>
        <tr>
            <td>Bearing</td>
            <td>{round(landing.bearing_from_home)}° from home</td>
        </tr>
        <tr>
            <td>Descent Rate</td>
            <td>
            {self.render_elevation(config, -landing['vel_v'])}/s,
            moving laterally
            {self.render_elevation(config, landing['vel_h'])}/s,
            heading {round(landing['heading'])}°
            </td>
        </tr>
        '''

        if ground_reception:
            body += '''
        <tr>
            <td colspan="2">Ground Reception</td>
        </tr>
            '''
            if elev:
                body += f'''
        <tr>
            <td>Elevation</td>
            <td>{self.render_elevation(config, elev)}</td>
        </tr>
                '''
        elif elev:
            time_to_landing = (landing['alt'] - elev) / -landing['vel_v']
            horiz_error = landing['vel_h'] * time_to_landing
            body += f'''
        <tr>
            <th colspan="2">Landing Estimation</th>
        </tr>
        <tr>
            <td>Ground Elev</td>
            <td>{self.render_elevation(config, elev)}</td>
        </tr>
        <tr>
            <td>Time to landing</td>
            <td>{round(time_to_landing)} s</td>
        </tr>
        <tr>
            <td>Search Radius</td>
            <td>{self.render_elevation(config, horiz_error)}</td>
        </tr>
            '''

        body += '''
    </table>
        '''

        return subj, body

    def send_email(self, config, flight, landing):
        subj, body = self.get_email_text(config, landing)

        # build mime message
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subj
        msg['From'] = constants.FROM_EMAIL_ADDR
        msg['To'] = config['email']

        # Generate map link for email
        t = landing['datetime']
        map_suffix = \
            f"{config['uuid_subscription']}/{t.year}/{t.month}/{t.day}-{t.hour}-{landing['lat']}-{landing['lon']}.jpg"
        map_url = os.path.join(EXTERNAL_IMAGES_URL) + map_suffix
        body += f'<p><img width="100%" src="{map_url}">'

        # Store map to external images root directory
        map_local_fn = os.path.join(self.args.external_images_root, map_suffix)
        map_dir = os.path.split(map_local_fn)[0]
        os.makedirs(map_dir, exist_ok=True)
        fig = self.get_email_image(config, 22, flight, landing)
        fig.savefig(map_local_fn, bbox_inches='tight')

        # all done
        body += '</body></html>'

        alternatives = MIMEMultipart('alternative')
        alternatives.attach(MIMEText(body, 'html', 'utf-8'))
        msg.attach(alternatives)

        if self.args.really_send:
            self.ses_client.send_raw_email(
                Source=constants.FROM_EMAIL_ADDR,
                Destinations=[constants.FROM_EMAIL_ADDR, config['email']],
                RawMessage={
                    'Data': msg.as_string(),
                },
            )
        else:
            print(f"Subj:\n{subj}\n")
            print(f"Body:\n{body}\n")

    def process_one(self, sondes, config):
        landing = self.get_nearest_landed_sonde(sondes, config)
        dist_from_home_mi = landing['dist_from_home_m'] / METERS_PER_MILE

        if dist_from_home_mi > config['max_distance_mi']:
            print(
                f"{config['email']}: Nearest landing is {dist_from_home_mi:.1f}, "
                f"more than max {config['max_distance_mi']}"
            )
            return

        # Query SondeHub for detail on the flight
        flight = self.get_sonde_data(params={
            'duration': '1d',
            'serial': landing['serial'],
        })

        self.send_email(config, flight, landing)

    def get_subscriber_data(self):
        table_definitions.create_table_clients(self)
        users = util.dynamodb_to_dataframe(self.user_table.scan)
        subs = util.dynamodb_to_dataframe(
            self.sub_table.scan,
            FilterExpression=Attr('active').eq(True)
        ).astype({
            'lat': float,
            'lon': float,
        })
        if subs.empty or users.empty:
            return pd.DataFrame()
        configs = subs.merge(users, left_on='subscriber', right_on='uuid', suffixes=('_subscription', '_user'))
        return configs

    def process_all(self):
        # Get subscription data
        configs = self.get_subscriber_data()

        # Get sonde data from SondeHub
        sondes = self.get_sonde_data(params={'duration': '12h'})

        # Filter the data down to just the last frame received from each sonde
        sondes = sondes.loc[sondes.groupby('serial')['frame'].idxmax()]

        for i, config in configs.iterrows():
            self.process_one(sondes, config)
            time.sleep(1)

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--really-send',
        default=False,
        action='store_true',
    )
    parser.add_argument(
        '--external-images-root',
        type=str,
        action='store',
        default=EXTERNAL_IMAGES_ROOT,
    )
    args = parser.parse_args(sys.argv[1:])

    return args

def main():
    args = get_args()

    if not args.really_send:
        args.external_images_root = "./test-maps"
        if not os.path.exists(args.external_images_root):
            os.makedirs(args.external_images_root)

    if not os.path.exists(args.external_images_root):
        raise Exception(f"External images root {args.external_images_root} does not exist")

    notifier = EmailNotifier(args, SondeHubTelemetryRetriever())
    notifier.process_all()

if __name__ == "__main__":
    main()
