#!/usr/bin/env python3

EXTERNAL_IMAGES_ROOT = '/mnt/storage/sondemaps'
EXTERNAL_IMAGES_URL = 'https://sondemaps.lectrobox.com/'

CONFIGS = [

    # Seattle
    {
        'name': 'seattle',
        'home_lat': 47.6426,
        'home_lon': -122.32271,
        'email_from': 'Seattle Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'jonh.sondenotify@jonh.net',
        ],
        'max_distance_mi': 300,
        'units': 'imperial',
        'tz': 'US/Pacific',
    },

    # Berkeley
    {
        'name': 'berkeley',
        'home_lat': 37.859,
        'home_lon': -122.270,
        'email_from': 'Berkeley Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'jonh.sondenotify@jonh.net',
            'david.jacobowitz+sonde@gmail.com',
        ],
        'max_distance_mi': 20,
        'units': 'imperial',
        'tz': 'US/Pacific',
    },

    # Kitchener
    {
        'name': 'kitchener',
        'home_lat': 43.46865,
        'home_lon': -80.49695,
        'email_from': 'Kitchener Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'info@bestforbees.com',
        ],
        'max_distance_mi': 77.6,
        'units': 'metric',
        'tz': 'US/Eastern',
    },
]

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from geographiclib.geodesic import Geodesic
from pyproj import Transformer
import argparse
import base64
import boto3
import contextily as cx
import dateparser
import datetime
import geocoder
import io
import json
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import os
import pandas as pd
import requests
import sys
import time

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

# other config
AWS_PROFILE = 'cambot-emailer'

# Clean up and annotate telemetry returned by sondehub
def cleanup_sonde_data(sondes):
    # Sometimes lat/lon comes as a string instead of float
    sondes = sondes.astype({
        'alt': float,
        'vel_v': float,
        'vel_h': float,
        'lat': float,
        'lon': float,
    })

    sondes['datetime'] = pd.to_datetime(sondes['datetime'])

    # Mark takeoffs and landings -- the earliest record and latest record for
    # each serial number
    takeoffs = sondes.groupby('serial')['datetime'].idxmin()
    sondes.loc[takeoffs, 'phase'] = 'takeoff'

    landings = sondes.groupby('serial')['datetime'].idxmax()
    sondes.loc[landings, 'phase'] = 'landing'

    return sondes

# Get sonde data from the same live API that the web site uses
def get_telemetry_once(params):
    def unpack_list():
        response = requests.get(SONDEHUB_DATA_URL, params=params)
        response.raise_for_status()
        for sonde, timeblock in response.json().items():
            for time, record in timeblock.items():
                yield record
    sondes = pd.DataFrame(unpack_list())
    sondes = cleanup_sonde_data(sondes)
    return sondes

def get_telemetry(params):
    retries = 0
    while retries <= MAX_SONDEHUB_RETRIES:
        if retries > 0:
            print("Sondehub data failure; retrying after a short sleep...")
            time.sleep((2**retries) * 4)
        retries += 1
        try:
            sondes = get_telemetry_once(params)
            if len(sondes) == 0:
                raise Exception("Got empty dataframe from Sondehub")
            return sondes
        except Exception as e:
            print(f"Couldn't get sondehub data: {e}")

    raise Exception(f"Couldn't get sondehub data, even after {MAX_SONDEHUB_RETRIES} retries")

def get_all_sondes():
    sondes = get_telemetry(params={'duration': '12h'})

    # Filter out launches left over from the prior launch cycle. We expect
    # sondes to be launched about 2 hours ago, but sondes launched 14 hours ago
    # that are still being received might show up here. Filter out any sondes
    # that have been transmitting data for more than 6 hours.
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    sondes = sondes.groupby('serial').filter(
        lambda g: now - g['datetime'].min() < datetime.timedelta(hours=6))

    return sondes

### Getting the nearest sonde

def annotate_with_distance(sondes, config):
    def get_path(sonde):
        path = Geodesic.WGS84.Inverse(config['home_lat'], config['home_lon'], sonde.lat, sonde.lon)
        return (
            path['s12'],
            (path['azi1'] + 360) % 360
        )

    # Annotate all landing records with distance from home
    sondes[['dist_from_home_m', 'bearing_from_home']] = sondes.apply(
        lambda s: get_path(s) if s['phase'] == 'landing' else (None, None),
        axis=1,
        result_type='expand')

    #f = sondes.sort_values('dist_from_home_mi')
    #print(f[f.phase == 'landing'].to_string())

    return sondes

def get_nearest_sonde_flight(sondes, config):
    sondes = annotate_with_distance(sondes, config)

    # Find the landing closest to home
    nearest_landing_idx = sondes[sondes['phase'] == 'landing']['dist_from_home_m'].idxmin()

    # Get the serial number of the nearest landing
    nearest_landing_serial = sondes.loc[nearest_landing_idx].serial

    # Return all data from the flight with the minimum landing distance

    # OLD: Just return the subsampled data from the overview result
    #nearest_landing_flight = sondes.loc[sondes.serial == nearest_landing_serial]

    # NEW: Query SondeHub for detail on the serial to get all data for that flight
    nearest_landing_flight = get_telemetry(params={
        'duration': '1d',
        'serial': nearest_landing_serial,
    })
    nearest_landing_flight = annotate_with_distance(nearest_landing_flight, config)

    return nearest_landing_flight


#### Drawing map

wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
def to_mercator_xy(lat, lon):
    return wgs84_to_mercator.transform(lat, lon)

MAP_WHITESPACE = 0.2

def get_limit(points):
    min_lat = min([point[0] for point in points])
    max_lat = max([point[0] for point in points])
    min_lon = min([point[1] for point in points])
    max_lon = max([point[1] for point in points])
    min_x, min_y = to_mercator_xy(min_lat, min_lon)
    max_x, max_y = to_mercator_xy(max_lat, max_lon)
    x_pad = (max_x - min_x) * MAP_WHITESPACE
    y_pad = (max_y - min_y) * MAP_WHITESPACE
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


def get_image(args, config, size, flight, landing):
    fig, ax = plt.subplots(figsize=(size, size))
    ax.axis('off')

    # Plot the balloon's path
    (flight_x, flight_y) = to_mercator_xy(flight.lat, flight.lon)
    ax.plot(flight_x, flight_y, color='red')

    # Plot a line from home to the landing point
    home_x, home_y = to_mercator_xy(config['home_lat'], config['home_lon'])
    sonde_x, sonde_y = to_mercator_xy(landing['lat'], landing['lon'])
    ax.plot([home_x, sonde_x], [home_y, sonde_y], color='blue', marker='*')

    # Find the limits of the map
    min_x, min_y, max_x, max_y, zoom = get_limit([
        [config['home_lat'], config['home_lon']],
        [landing['lat'], landing['lon']],
    ])
    ax.set_xlim([min_x, max_x])
    ax.set_ylim([min_y, max_y])
    print(f"{config['name']}: downloading at zoomlevel {zoom}")

    cx.add_basemap(
        ax,
        zoom=zoom,
        #source=cx.providers.OpenStreetMap.Mapnik,
        source=cx.providers.CyclOSM,
        #source=cx.providers.Stamen.Terrain,
        #source=cx.providers.Stamen.TopOSMFeatures,
    )
    fig.tight_layout()

    if not args.really_send:
        fig.savefig(f"test-{config['name']}.jpg", bbox_inches='tight')

    return fig


### Sending email

def get_elev(lat, lon):
    resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
        'x': lon,
        'y': lat,
        'units': 'Meters',
        'wkid': '4326',
        'includeDate': 'True',
    })
    if resp.status_code == 200:
        return float(resp.json()['value'])
    else:
        return None

def render_elevation(config, meters):
    if config['units'] == 'imperial':
        feet = meters / METERS_PER_FOOT
        return f"{round(feet):,}'"
    else:
        return f"{round(meters):,}m"

def render_distance(config, meters):
    if config['units'] == 'imperial':
        miles = meters / METERS_PER_MILE
        return f"{round(miles):,} miles"
    else:
        km = meters / METERS_PER_KM
        return f"{round(km):,}km"

def process(args, sondes, config):
    flight = get_nearest_sonde_flight(sondes, config)
    landing = flight.iloc[flight['datetime'].idxmax()]

    dist_from_home_mi = landing['dist_from_home_m'] / METERS_PER_MILE

    if dist_from_home_mi > config['max_distance_mi']:
        print(f"{config['name']}: Nearest landing is {dist_from_home_mi:.1f}, more than max {config['max_distance_mi']}")
        return

    # attempt a geocode and DEM lookup
    geo = geocoder.osm(f"{landing['lat']}, {landing['lon']}")
    elev = get_elev(landing['lat'], landing['lon'])

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
    landing_localtime = landing.datetime.tz_convert(config['tz'])

    # subject line
    subj = ""
    if ground_reception:
        subj += 'GROUND RECEPTION! '
    subj += f"{landing_localtime.month_name()} {landing_localtime.day} "
    subj += "morning" if landing_localtime.hour < 12 else "afternoon"
    subj += f" sonde landed "
    subj += render_distance(config, landing['dist_from_home_m'])
    subj += f" from home, bearing {round(landing.bearing_from_home)}°"
    if place:
        subj += f" ({place})"

    # body
    uploaders = [u['uploader_callsign'] for u in landing['uploaders']]
    body = f'Sonde <a href="{SONDEHUB_MAP_URL.format(serial=landing.serial)}">{landing.serial}</a> '
    body += f'was last heard by {", ".join(uploaders)} '
    body += f'at {landing_localtime.strftime("%Y-%m-%d %H:%M:%S %Z")} '
    body += f'as it descended through '
    body += render_elevation(config, landing['alt'])
    body += '. '
    body += f'It was last heard at <a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a>, '
    body += f'which is about '
    body += render_distance(config, landing['dist_from_home_m'])
    body += f' from home at a bearing of {round(landing.bearing_from_home)}°'
    if place:
        body += f', in {place}'
    body += '. '
    if geo and geo.address:
        body += f'The nearest known address is {geo.address}. '

    body += '<p>When last heard, the sonde was descending at '
    body += render_elevation(config, -landing['vel_v']) + '/s '
    body += 'and moving laterally at '
    body += render_elevation(config, landing['vel_h']) + '/s, heading '
    body += f"{round(landing['heading'])}°. "

    if ground_reception:
        body += '<b>The sonde appears to still be in contact with receivers while stationary, '
        body += 'so the last-heard location may be the actual landing site!</b> '

        if elev:
            body += f'The ground elevation at the last-heard location is '
            body += render_elevation(config, elev)
            body += '. '

    elif elev:
        body += f'The ground elevation at the last-heard location is '
        body += render_elevation(config, elev)
        body += ', so the sonde was last heard '
        time_to_landing = (landing['alt'] - elev) / -landing['vel_v']
        body += f'{round(time_to_landing)}s from landing, implying a landing position about '
        horiz_error = landing['vel_h'] * time_to_landing
        body += render_elevation(config, horiz_error)
        body += ' away.'

    # build mime message
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subj
    msg['From'] = config['email_from']
    msg['To'] = ",".join(config['email_to'])

    if EXTERNAL_IMAGES_ROOT:
        # map as link to external web site
        map_suffix = f"{config['name']}/{landing_localtime.year}/{landing_localtime.month}/{landing_localtime.day}-{landing_localtime.hour}-{landing.lat}-{landing.lon}.jpg"
        map_local_fn = os.path.join(EXTERNAL_IMAGES_ROOT, map_suffix)
        map_dir = os.path.split(map_local_fn)[0]
        os.makedirs(map_dir, exist_ok=True)
        map_url = os.path.join(EXTERNAL_IMAGES_URL) + map_suffix
        fig = get_image(args, config, 22, flight, landing)
        fig.savefig(map_local_fn, bbox_inches='tight')
        body += f'<p><img width="100%" src="{map_url}">'
    else:
        # map as attachment
        image_cid = make_msgid(domain='lectrobox.com')
        body += f'<p><img width="100%" src="cid:{image_cid}">'

        img = io.BytesIO()
        fig = get_image(args, config, 12, flight, landing)
        fig.savefig(img, format='jpg', bbox_inches='tight')
        img.seek(0)
        img_att = MIMEImage(img.read(), name='map.jpg')
        img_att.add_header('Content-ID', f'<{image_cid}>')
        msg.attach(img_att)

    alternatives = MIMEMultipart('alternative')
    alternatives.attach(MIMEText(body, 'html', 'utf-8'))
    msg.attach(alternatives)

    if args.really_send:
        session = boto3.Session(profile_name=AWS_PROFILE)
        client = session.client('ses', region_name = 'us-west-2')
        client.send_raw_email(
            Source=config['email_from'],
            Destinations=config['email_to'],
            RawMessage={
                'Data': msg.as_string(),
            },
        )
    else:
        print(f"Subj:\n{subj}\n")
        print(f"Body:\n{body}\n")

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--really-send',
        default=False,
        action='store_true',
    )
    args = parser.parse_args(sys.argv[1:])

    return args

def main():
    args = get_args()

    global EXTERNAL_IMAGES_ROOT
    if not os.path.exists(EXTERNAL_IMAGES_ROOT):
        if args.really_send:
            raise Exception(f"External images root {EXTERNAL_IMAGES_ROOT} does not exist")
        else:
            EXTERNAL_IMAGES_ROOT = None

    sondes = get_all_sondes()

    for config in CONFIGS:
        process(args, sondes, config)
        time.sleep(1)

if __name__ == "__main__":
    main()
