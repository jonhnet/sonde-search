#!/usr/bin/env python3

CONFIGS = [

    # Seattle
    {
        'home_lat': 47.6426,
        'home_lon': -122.32271,
        'email_from': 'Seattle Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'jonh.sondenotify@jonh.net',
        ],
        'max_distance_mi': 300,
    },

    # Berkeley
    {
        'home_lat': 37.859,
        'home_lon': -122.270,
        'email_from': 'Berkeley Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'jonh.sondenotify@jonh.net',
            'david.jacobowitz+sonde@gmail.com',
        ],
        'max_distance_mi': 25,
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
import os
import pandas as pd
import requests
import sondehub
import sys
import time

matplotlib.use('Agg')

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

AWS_PROFILE = 'cambot-emailer'
METERS_PER_MILE = 1609.34
METERS_PER_FOOT = 0.3048
SONDEHUB_DATA_URL = 'https://api.v2.sondehub.org/sondes/telemetry?duration=6h'
MAX_SONDEHUB_RETRIES = 6
SONDEHUB_MAP_URL = 'https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f={serial}&q={serial}'
GMAP_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

# This is the old-style version that uses the sondehub python API, which goes to
# sondehub's public S3 bucket for data. However, it's a few hours behind, and
# we'd like data closer to live.
def get_sonde_telemetry_s3(date):
    # get data from all sondes that had a flight today. Sondehub returns 3
    # points per sonde: first reception, highest reception, and last reception.
    return pd.DataFrame(sondehub.download(
        datetime_prefix=f"{date.year:4}/{date.month:02}/{date.day:02}")
    )

# Get sonde data from the same live API that the web site uses
def get_sonde_telemetry_api():
    def unpack_list():
        response = requests.get(SONDEHUB_DATA_URL)
        response.raise_for_status()
        for sonde, timeblock in response.json().items():
            for time, record in timeblock.items():
                yield record
    return pd.DataFrame(unpack_list())

def get_telemetry(args):
    if args.date:
        return get_sonde_telemetry_s3(args.date)
    else:
        return get_sonde_telemetry_api()

def get_telemetry_with_retries(args):
    retries = 0
    while retries <= MAX_SONDEHUB_RETRIES:
        if retries > 0:
            print("Sondehub data failure; retrying after a short sleep...")
            time.sleep((2**retries) * 4)
        retries += 1
        try:
            sondes = get_telemetry(args)
            if len(sondes) == 0:
                raise Exception("Got empty dataframe from Sondehub")
            return sondes
        except Exception as e:
            print(f"Couldn't get sondehub data: {e}")

    raise Exception(f"Couldn't get sondehub data, even after {MAX_SONDEHUB_RETRIES} retries")

def get_all_sondes(args):
    sondes = get_telemetry_with_retries(args)

    # Sometimes lat/lon comes as a string instead of float
    sondes = sondes.astype({
        'alt': float,
        'vel_v': float,
        'lat': float,
        'lon': float,
    })

    sondes['datetime'] = pd.to_datetime(sondes['datetime'])

    # If no particular date has been requested, apply a cutoff time to make sure
    # we're only examining the latest launches
    if not args.date:
        utc_cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=6)
        sondes = sondes.loc[sondes.datetime >= utc_cutoff]

    # Mark takeoffs and landings -- the earliest ascent record and latest
    # descent record for each serial number
    ascents = sondes.loc[sondes.vel_v > 0]
    takeoffs = ascents.groupby('serial')['datetime'].idxmin()
    sondes.loc[takeoffs, 'phase'] = 'takeoff'

    descents = sondes.loc[sondes.vel_v < 0]
    landings = descents.groupby('serial')['datetime'].idxmax()
    sondes.loc[landings, 'phase'] = 'landing'

    return sondes


### Getting the nearest sonde

def get_nearest_sonde_flight(sondes, config):
    def get_path(sonde):
        path = Geodesic.WGS84.Inverse(config['home_lat'], config['home_lon'], sonde.lat, sonde.lon)
        return (
            path['s12'] / METERS_PER_MILE,
            (path['azi1'] + 360) % 360
        )

    # Annotate all landing records with distance from home
    sondes[['dist_from_home_mi', 'bearing_from_home']] = sondes.apply(
        lambda s: get_path(s) if s.phase == 'landing' else (None, None),
        axis=1,
        result_type='expand')

    #f = sondes.sort_values('dist_from_home_mi')
    #print(f[f.phase == 'landing'].to_string())

    # Find the landing closest to home
    nearest_landing_idx = sondes[sondes.phase == 'landing'].dist_from_home_mi.idxmin()

    # Get the serial number of the nearest landing
    nearest_landing_serial = sondes.loc[nearest_landing_idx].serial

    # Return all data from the flight with the minimum landing distance
    nearest_landing_flight = sondes.loc[sondes.serial == nearest_landing_serial]

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
    return min_x, min_y, max_x, max_y


def get_image(args, config, flight, landing):
    fig, ax = plt.subplots(figsize=(12, 12))
    ax.axis('off')

    # Plot the balloon's path
    (flight_x, flight_y) = to_mercator_xy(flight.lat, flight.lon)
    ax.plot(flight_x, flight_y, color='red')

    # Plot a line from home to the landing point
    home_x, home_y = to_mercator_xy(config['home_lat'], config['home_lon'])
    sonde_x, sonde_y = to_mercator_xy(landing['lat'], landing['lon'])
    ax.plot([home_x, sonde_x], [home_y, sonde_y], color='blue', marker='*')

    # Find the limits of the map
    min_x, min_y, max_x, max_y = get_limit([
        [config['home_lat'], config['home_lon']],
        [landing['lat'], landing['lon']],
    ])
    ax.set_xlim([min_x, max_x])
    ax.set_ylim([min_y, max_y])

    cx.add_basemap(
        ax,
        #zoom=10,
        source=cx.providers.OpenStreetMap.Mapnik,
    )
    fig.tight_layout()

    if not args.really_send:
        fig.savefig("test.jpg", bbox_inches='tight')

    return fig


### Sending email

def process(args, sondes, config):
    flight = get_nearest_sonde_flight(sondes, config)
    landing = flight.loc[flight.phase == 'landing'].iloc[0]

    if landing.dist_from_home_mi > config['max_distance_mi']:
        print(f"{config['email_from']}: Nearest landing is {landing.dist_from_home_mi:.1f}, more than max")
        return

    last_alt_ft = round(landing['alt'] / METERS_PER_FOOT)

    # attempt a geocode
    geo = geocoder.osm(f"{landing.lat}, {landing.lon}")

    place = ""
    if geo and geo.county:
        if geo.town:
            place += geo.town + ", "
        if geo.city:
            place += geo.city + ", "
        place += geo.county

    # timezone can be part of config eventually
    landing_localtime = landing.datetime.tz_convert('US/Pacific')

    # subject line
    subj = f"{landing_localtime.month_name()} {landing_localtime.day} "
    subj += "morning" if landing_localtime.hour < 12 else "afternoon"
    subj += f" sonde landed {round(landing.dist_from_home_mi)}mi from home,"
    subj += f" bearing {round(landing.bearing_from_home)}°"
    if place:
        subj += f" ({place})"

    # body
    body = f'Sonde <a href="{SONDEHUB_MAP_URL.format(serial=landing.serial)}">{landing.serial}</a> '
    body += f'was last heard at {landing_localtime.strftime("%Y-%m-%d %H:%M:%S")} Pacific time '
    body += f"as it descended through {last_alt_ft:,}'. "
    body += f'It was last heard at <a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a>, '
    body += f'which is about {round(landing.dist_from_home_mi)} miles from home at a bearing of {round(landing.bearing_from_home)}°'
    if place:
        body += f', in {place}'
    body += ". "
    if geo and geo.address:
        body += f' The nearest known address is {geo.address}.'

    if last_alt_ft > 15000:
        body += '<p>NOTE: Because its last-heard altitude was so high, its actual landing location is several miles away.'

    if not args.really_send:
        print(f"Subj:\n{subj}\n")
        print(f"Body:\n{body}\n")

    image_cid = make_msgid(domain='lectrobox.com')
    body += f'<p><img width="100%" src="cid:{image_cid}">'

    # build mime message including map attachment
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subj
    msg['From'] = config['email_from']
    msg['To'] = ",".join(config['email_to'])
    alternatives = MIMEMultipart('alternative')
    alternatives.attach(MIMEText(body, 'html', 'utf-8'))
    msg.attach(alternatives)

    img = io.BytesIO()
    fig = get_image(args, config, flight, landing)
    fig.savefig(img, format='jpg', bbox_inches='tight')
    img.seek(0)
    img_att = MIMEImage(img.read(), name='map.jpg')
    img_att.add_header('Content-ID', f'<{image_cid}>')
    msg.attach(img_att)

    session = boto3.Session(profile_name=AWS_PROFILE)
    client = session.client('ses', region_name = 'us-west-2')

    if args.really_send:
        client.send_raw_email(
            Source=config['email_from'],
            Destinations=config['email_to'],
            RawMessage={
                'Data': msg.as_string(),
            },
        )

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--really-send',
        default=False,
        action='store_true',
    )
    parser.add_argument(
        '--date',
        action='store',
    )
    args = parser.parse_args(sys.argv[1:])

    if args.date:
        args.date = dateparser.parse(args.date)

    return args

def main():
    args = get_args()

    sondes = get_all_sondes(args)

    for config in CONFIGS:
        process(args, sondes, config)

if __name__ == "__main__":
    main()
