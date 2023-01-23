#!/usr/bin/env python3

from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from geographiclib.geodesic import Geodesic
from pyproj import Transformer
import base64
import boto3
import contextily as cx
import datetime
import io
import matplotlib.pyplot as plt
import os
import pandas as pd
import sondehub

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

LAT_MIN = 45
LAT_MAX = 49
LON_MIN = -125
LON_MAX = -121

HOME_LAT = 47.6485
HOME_LON = -122.3502

METERS_PER_MILE = 1609.34
DEBUG = False

AWS_PROFILE = 'cambot-emailer'
FROM_ADDR = 'Seattle Sonde Notifier <jelson@lectrobox.com>'

TO_ADDRS = [
    'jelson@gmail.com',
    #'jonh.sondenotify@jonh.net',
    
]
SONDEHUB_URL = 'https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f={serial}&q={serial}'
GMAP_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

wgs84_to_mercator = Transformer.from_crs(crs_from='EPSG:4326', crs_to='EPSG:3857')
def to_mercator_xy(lat, lon):
    return wgs84_to_mercator.transform(lat, lon)
    
def get_latest_sonde():
    now = datetime.datetime.utcnow()
    df = pd.DataFrame(sondehub.download(
        datetime_prefix=f"{now.year:4}/{now.month:02}/{now.day:02}")
    )
    local = df.loc[
        (df.lat >= LAT_MIN) &
        (df.lat <= LAT_MAX) &
        (df.lon >= LON_MIN) &
        (df.lon <= LON_MAX)
    ]

    if DEBUG:
        print(local)
        
    landings = local.loc[
        (local.vel_v < 0) &
        (local.alt < 10000)
    ].sort_values(by='datetime')

    if DEBUG:
        print(landings)

    return landings.iloc[-1]

MAP_WHITESPACE = 0.5

def get_limit(points):
    min_lat = min([point[0]-MAP_WHITESPACE for point in points])
    max_lat = max([point[0]+MAP_WHITESPACE for point in points])
    min_lon = min([point[1]-MAP_WHITESPACE for point in points])
    max_lon = max([point[1]+MAP_WHITESPACE for point in points])
    min_x, min_y = to_mercator_xy(min_lat, min_lon)
    max_x, max_y = to_mercator_xy(max_lat, max_lon)
    return min_x, min_y, max_x, max_y


def get_image(landing):
    home_x, home_y = to_mercator_xy(HOME_LAT, HOME_LON)
    sonde_x, sonde_y = to_mercator_xy(landing['lat'], landing['lon'])

    fig, ax = plt.subplots(figsize=(9, 9))
    fig.set_dpi(40)
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

    if DEBUG:
        fig.savefig("test.jpg", bbox_inches='tight')
    return fig


def main():
    landing = get_latest_sonde()
    path = Geodesic.WGS84.Inverse(HOME_LAT, HOME_LON, landing.lat, landing.lon)
    if DEBUG:
        print(path)

    landing_time = pd.to_datetime(landing['datetime']).tz_convert('US/Pacific')
    dist = round(path['s12'] / METERS_PER_MILE)
    bearing = (round(path['azi1']) + 360) % 360
    #subj = f"Sonde landed at {landing_time.hour}:{landing_time.minute:02}, {dist}mi from home, bearing {bearing}°"
    subj = f"Sonde landed {dist}mi from home, bearing {bearing}°"
    body = f'Sonde <a href="{SONDEHUB_URL.format(serial=landing.serial)}">{landing.serial}</a> '
    body += f'was last heard from at {landing_time.strftime("%Y-%m-%d %H:%M:%S")} Pacific time. '
    body += f'It landed near <a href="{GMAP_URL.format(lat=landing.lat, lon=landing.lon)}">{landing.lat}, {landing.lon}</a>, '
    body += f'which is about {dist} miles from home at a bearing of {bearing}°.'

    if DEBUG:
        print(subj)
        print(body)

    image_cid = make_msgid(domain='lectrobox.com')
    body += f'<p><img width="100%" src="cid:{image_cid}">'

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subj
    msg['From'] = FROM_ADDR
    msg['To'] = ",".join(TO_ADDRS)
    alternatives = MIMEMultipart('alternative')
    alternatives.attach(MIMEText(body, 'html', 'utf-8'))
    msg.attach(alternatives)

    img = io.BytesIO()
    fig = get_image(landing)
    fig.savefig(img, format='jpg', bbox_inches='tight')
    img.seek(0)
    img_att = MIMEImage(img.read(), name='map.jpg')
    img_att.add_header('Content-ID', f'<{image_cid}>')
    msg.attach(img_att)

    session = boto3.Session(profile_name=AWS_PROFILE)
    client = session.client('ses', region_name = 'us-west-2')

    client.send_raw_email(
        Source=FROM_ADDR,
        Destinations=TO_ADDRS,
        RawMessage={
            'Data': msg.as_string(),
        },
    )

"""
    client.send_email(
        Source=FROM_ADDR,
        Destination={
            'ToAddresses': TO_ADDRS,
        },
        Message={
            'Subject': {
                'Charset': 'UTF-8',
                'Data': subj,
            },
            'Body': {
                'Html': {
                    'Charset': 'UTF-8',
                    'Data': body,
                },
            },
        },
    )
"""

if __name__ == "__main__":
    main()
    
