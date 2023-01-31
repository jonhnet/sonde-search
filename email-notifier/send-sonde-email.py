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
        'max_distance_miles': 200,
    },

    # Oakland
    {
        'home_lat': 37.859,
        'home_lon': -122.270,
        'email_from': 'Berkeley Sonde Notifier <jelson@lectrobox.com>',
        'email_to': [
            'jelson@gmail.com',
            'jonh.sondenotify@jonh.net',
            'david.jacobowitz+sonde@gmail.com',
        ],
        'max_distance_miles': 25,
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
import matplotlib.pyplot as plt
import os
import pandas as pd
import requests
import sondehub
import sys

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

AWS_PROFILE = 'cambot-emailer'
METERS_PER_MILE = 1609.34
SONDEHUB_DATA_URL = 'https://api.v2.sondehub.org/sondes/telemetry?duration=12h'
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

def get_sonde_telemetry_api():
    def unpack_list():
        api_retval = requests.get(SONDEHUB_DATA_URL).json()
        for sonde, timeblock in api_retval.items():
            for time, record in timeblock.items():
                yield record
    return pd.DataFrame(unpack_list())

def get_all_sondes(args):
    if args.date:
        sondes = get_sonde_telemetry_s3(args.date)
    else:
        sondes = get_sonde_telemetry_api()

    # Sometimes lat/lon comes as a string instead of float
    sondes = sondes.astype({
        'alt': float,
        'vel_v': float,
        'lat': float,
        'lon': float,
    })

    sondes['datetime'] = pd.to_datetime(sondes['datetime'])

    # Mark takeoffs and landings -- the earliest ascent record and latest
    # descent record for each serial number
    ascents = sondes.loc[(sondes.vel_v > 0) & (sondes.alt < 15000)]
    takeoffs = ascents.groupby('serial')['datetime'].idxmin()
    sondes.loc[takeoffs, 'phase'] = 'takeoff'

    descents = sondes.loc[(sondes.vel_v < 0) & (sondes.alt < 15000)]
    landings = descents.groupby('serial')['datetime'].idxmax()
    sondes.loc[landings, 'phase'] = 'landing'

    return sondes


### Getting the nearest sonde

def get_path(sonde, config):
    path = Geodesic.WGS84.Inverse(config['home_lat'], config['home_lon'], sonde.lat, sonde.lon)
    return {
        'dist_from_home_mi': round(path['s12'] / METERS_PER_MILE),
        'bearing_from_home': (round(path['azi1']) + 360) % 360,
    }

def get_nearest_sonde_flight(sondes, config):
    # Annotate all sondes with distance from home
    sondes = pd.concat([
        sondes,
        pd.DataFrame.from_records(sondes.apply(get_path, config=config, axis=1))
    ], axis=1)

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

MAP_WHITESPACE = 0.5

def get_limit(points):
    min_lat = min([point[0]-MAP_WHITESPACE for point in points])
    max_lat = max([point[0]+MAP_WHITESPACE for point in points])
    min_lon = min([point[1]-MAP_WHITESPACE for point in points])
    max_lon = max([point[1]+MAP_WHITESPACE for point in points])
    min_x, min_y = to_mercator_xy(min_lat, min_lon)
    max_x, max_y = to_mercator_xy(max_lat, max_lon)
    return min_x, min_y, max_x, max_y


def get_image(args, config, landing):
    home_x, home_y = to_mercator_xy(config['home_lat'], config['home_lon'])
    sonde_x, sonde_y = to_mercator_xy(landing['lat'], landing['lon'])

    fig, ax = plt.subplots(figsize=(12, 12))
    ax.axis('off')
    ax.plot([home_x, sonde_x], [home_y, sonde_y], marker='*')
    min_x, min_y, max_x, max_y = get_limit([
        [config['home_lat'], config['home_lon']],
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

    if not args.really_send:
        fig.savefig("test.jpg", bbox_inches='tight')

    return fig


### Sending email

def process(args, sondes, config):
    flight = get_nearest_sonde_flight(sondes, config)
    landing = flight.loc[flight.phase == 'landing'].iloc[0]

    # attempt a geocode
    geo = geocoder.osm(f"{landing.lat}, {landing.lon}")

    place = ""
    if geo and geo.county:
        if geo.town:
            place += geo.town + ", "
        if geo.city:
            place += geo.city + ", "
        place += geo.county

    # can be part of config eventually
    landing_localtime = landing.datetime.tz_convert('US/Pacific')

    # subject line
    subj = f"{landing_localtime.month_name()} {landing_localtime.day} "
    subj += "morning" if landing_localtime.hour < 12 else "afternoon"
    subj += f" sonde landed {landing.dist_from_home_mi}mi from home,"
    subj += f" bearing {landing.bearing_from_home}°"
    if place:
        subj += f" ({place})"

    # body
    body = f'Sonde <a href="{SONDEHUB_MAP_URL.format(serial=landing.serial)}">{landing.serial}</a> '
    body += f'was last heard at {landing_localtime.strftime("%Y-%m-%d %H:%M:%S")} Pacific time. '
    body += f'It landed near <a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a>, '
    body += f'which is about {landing.dist_from_home_mi} miles from home at a bearing of {landing.bearing_from_home}°.'
    if place:
        body += f' It landed in {place}.'
    if geo and geo.address:
        body += f' The nearest known address is {geo.address}.'

    if not args.really_send:
        print(subj)
        print(body)

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
    fig = get_image(args, config, landing)
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
