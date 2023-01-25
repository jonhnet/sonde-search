#!/usr/bin/env python3

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
import datetime
import io
import json
import matplotlib.pyplot as plt
import os
import pandas as pd
import requests
import sondehub
import sys

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

LAT_MIN = 45
LAT_MAX = 49
LON_MIN = -125
LON_MAX = -121

HOME_LAT = 47.6485
HOME_LON = -122.3502

METERS_PER_MILE = 1609.34

AWS_PROFILE = 'cambot-emailer'
FROM_ADDR = 'Seattle Sonde Notifier <jelson@lectrobox.com>'

TO_ADDRS = [
    'jelson@gmail.com',
    'jonh.sondenotify@jonh.net',
]

SONDEHUB_DATA_URL = 'https://api.v2.sondehub.org/sondes/telemetry?duration=6h'
SONDEHUB_MAP_URL = 'https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f={serial}&q={serial}'
GMAP_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
def to_mercator_xy(lat, lon):
    return wgs84_to_mercator.transform(lat, lon)

# This is the old-style version that uses the sondehub python API, which goes to
# sondehub's public S3 bucket for data. However, it's a few hours behind, and
# we'd like data closer to live.
def get_sonde_telemetry_s3():
    now = datetime.datetime.utcnow()

    # get data from all sondes that had a flight today. Sondehub returns 3
    # points per sonde: first reception, highest reception, and last reception.
    return pd.DataFrame(sondehub.download(
        datetime_prefix=f"{now.year:4}/{now.month:02}/{now.day:02}")
    )

def get_sonde_telemetry_api():
    def unpack_list():
        api_retval = requests.get(SONDEHUB_DATA_URL).json()
        for sonde, timeblock in api_retval.items():
            for time, record in timeblock.items():
                yield record
    return pd.DataFrame(unpack_list())

def get_latest_sonde():
    #df = get_sonde_telemetry_s3()
    df = get_sonde_telemetry_api()

    # Sometimes lat/lon comes as a string instead of float
    df.lat = df.lat.astype(float)
    df.lon = df.lon.astype(float)

    # find only sondes in the home area
    local = df.loc[
        (df.lat >= LAT_MIN) &
        (df.lat <= LAT_MAX) &
        (df.lon >= LON_MIN) &
        (df.lon <= LON_MAX)
    ]

    if args.debug:
        print(local)

    # Find only descents:
    landings = local.loc[
        (local.vel_v < 0) &
        (local.alt < 10000)
    ]

    if args.debug:
        print(landings)

    # Sort by date and return just the latest landing
    return landings.sort_values(by='datetime').iloc[-1]


MAP_WHITESPACE = 0.5

def get_limit(points):
    min_lat = min([point[0]-MAP_WHITESPACE for point in points])
    max_lat = max([point[0]+MAP_WHITESPACE for point in points])
    min_lon = min([point[1]-MAP_WHITESPACE for point in points])
    max_lon = max([point[1]+MAP_WHITESPACE for point in points])
    min_x, min_y = to_mercator_xy(min_lat, min_lon)
    max_x, max_y = to_mercator_xy(max_lat, max_lon)
    return min_x, min_y, max_x, max_y


def get_image(args, landing):
    home_x, home_y = to_mercator_xy(HOME_LAT, HOME_LON)
    sonde_x, sonde_y = to_mercator_xy(landing['lat'], landing['lon'])

    fig, ax = plt.subplots(figsize=(12, 12))
    ax.axis('off')
    ax.plot([home_x, sonde_x], [home_y, sonde_y], marker='*')
    min_x, min_y, max_x, max_y = get_limit([
        [HOME_LAT, HOME_LON],
        [landing['lat'], landing['lon']],
    ])
    ax.set_xlim([min_x, max_x])
    ax.set_ylim([min_y, max_y])

    cx.add_basemap(
        ax,
        zoom=9,
        source=cx.providers.OpenStreetMap.Mapnik,
    )
    fig.tight_layout()

    if args.debug:
        fig.savefig("test.jpg", bbox_inches='tight')
    return fig


def main(args):
    landing = get_latest_sonde()
    path = Geodesic.WGS84.Inverse(HOME_LAT, HOME_LON, landing.lat, landing.lon)
    if args.debug:
        print(path)

    landing_time = pd.to_datetime(landing['datetime']).tz_convert('US/Pacific')
    dist = round(path['s12'] / METERS_PER_MILE)
    bearing = (round(path['azi1']) + 360) % 360

    # subject line
    subj = f"{landing_time.month_name()} {landing_time.day} "
    subj += "morning" if landing_time.hour < 12 else "afternoon"
    subj += f" sonde landed {dist}mi from home, bearing {bearing}°"

    # body
    body = f'Sonde <a href="{SONDEHUB_MAP_URL.format(serial=landing.serial)}">{landing.serial}</a> '
    body += f'was last heard from at {landing_time.strftime("%Y-%m-%d %H:%M:%S")} Pacific time. '
    body += f'It landed near <a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a>, '
    body += f'which is about {dist} miles from home at a bearing of {bearing}°.'

    if args.debug:
        print(subj)
        print(body)

    image_cid = make_msgid(domain='lectrobox.com')
    body += f'<p><img width="100%" src="cid:{image_cid}">'

    # build mime message including map attachment
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subj
    msg['From'] = FROM_ADDR
    msg['To'] = ",".join(TO_ADDRS)
    alternatives = MIMEMultipart('alternative')
    alternatives.attach(MIMEText(body, 'html', 'utf-8'))
    msg.attach(alternatives)

    img = io.BytesIO()
    fig = get_image(args, landing)
    fig.savefig(img, format='jpg', bbox_inches='tight')
    img.seek(0)
    img_att = MIMEImage(img.read(), name='map.jpg')
    img_att.add_header('Content-ID', f'<{image_cid}>')
    msg.attach(img_att)

    session = boto3.Session(profile_name=AWS_PROFILE)
    client = session.client('ses', region_name = 'us-west-2')

    if not args.debug:
        client.send_raw_email(
            Source=FROM_ADDR,
            Destinations=TO_ADDRS,
            RawMessage={
                'Data': msg.as_string(),
            },
        )

def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-d', '--debug',
        default=False,
        action='store_true',
    )
    return parser.parse_args(sys.argv[1:])

if __name__ == "__main__":
    args = get_args()
    main(args)
