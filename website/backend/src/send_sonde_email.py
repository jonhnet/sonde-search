#!/usr/bin/env python3

EXTERNAL_IMAGES_ROOT = '/mnt/storage/sondemaps'
EXTERNAL_IMAGES_URL = 'https://maps.sondesearch.lectrobox.com/'

from boto3.dynamodb.conditions import Key, Attr
from decimal import Decimal
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from geographiclib.geodesic import Geodesic
from typing import Optional
import argparse
import boto3
import html
import contextily as cx  # type: ignore
import geocoder
import matplotlib
import matplotlib.figure
import matplotlib.pyplot as plt
import os
import pandas as pd
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(__file__))
import constants
import table_definitions
import util

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../'))
import lib.map_utils as map_utils

matplotlib.use('Agg')

cx.set_cache_dir(os.path.expanduser("~/.cache/geotiles"))

# conversion factors
METERS_PER_MILE = 1609.34
METERS_PER_KM = 1000
METERS_PER_FOOT = 0.3048

# URLs for email body
SONDEHUB_MAP_URL = 'https://sondehub.org/#!mt=Mapnik&mz=9&qm=12h&f={serial}&q={serial}'
GMAP_URL = 'https://www.google.com/maps/search/?api=1&query={lat},{lon}'

# random other constants
DEV_EMAIL = 'jelson@gmail.com'
SONDE_HISTORY_LOOKBACK_TIME_SEC = 86400


class EmailNotifier:
    def __init__(self, args: argparse.Namespace, retriever: util.SondeHubRetrieverBase) -> None:
        self.args = args
        self.retriever = retriever
        self.ses_client = boto3.client('ses')
        self.map_utils = map_utils.MapUtils()

    #
    # Sonde data retrieval
    #

    ### Getting the nearest sonde
    def annotate_with_distance(self, sondes: pd.DataFrame, sub: pd.Series) -> pd.DataFrame:
        def get_path(sonde):
            # type: ignore[attr-defined] on next line
            path = Geodesic.WGS84.Inverse(sub['lat'], sub['lon'], sonde['lat'], sonde['lon'])
            return (
                path['s12'],
                (path['azi1'] + 360) % 360
            )

        # Annotate all landing records with distance from home
        sondes[['dist_from_home_m', 'bearing_from_home']] = sondes.apply(
            get_path,
            axis=1,
            result_type='expand')

        # sonde still in contact from the ground?
        sondes['ground_reception'] = (sondes['vel_v'].abs() < 1) & (sondes['vel_h'].abs() < 1)

        return sondes

    ####
    #### Drawing map
    ####

    def get_email_image(
        self, sub: pd.Series, size: int, flight: pd.DataFrame, landing: pd.Series
    ) -> matplotlib.figure.Figure:
        fig, ax = plt.subplots(figsize=(size, size))
        ax.axis('off')
        ax.set_aspect('equal')

        # Plot the balloon's path
        (flight_x, flight_y) = self.map_utils.to_mercator_xy(flight.lat, flight.lon)
        ax.plot(flight_x, flight_y, color='red')

        # Plot a line from home to the landing point
        home_x, home_y = self.map_utils.to_mercator_xy(sub['lat'], sub['lon'])
        sonde_x, sonde_y = self.map_utils.to_mercator_xy(landing['lat'], landing['lon'])
        ax.plot([home_x, sonde_x], [home_y, sonde_y], color='blue', marker='*')
        ax.annotate(
            xy=(home_x, home_y),
            text='home',
            xytext=(10, 0),
            textcoords='offset points',
            arrowprops=dict(arrowstyle='-'),
        )

        map_limits = [
            [sub['lat'], sub['lon']],
            [landing['lat'], landing['lon']],
        ]

        # If the last receiver has a report lat/lon, plot a line from it to the
        # landing point
        if not pd.isna(landing['uploader_position']):
            rx_lat, rx_lon = [float(f) for f in landing['uploader_position'].split(',')]
            rx_x, rx_y = self.map_utils.to_mercator_xy(rx_lat, rx_lon)
            ax.plot([rx_x, sonde_x], [rx_y, sonde_y], color='springgreen', marker='*')
            ax.annotate(
                xy=(rx_x, rx_y),
                text=f"rx ({html.escape(landing['uploader_callsign'])})",
                xytext=(10, 0),
                textcoords='offset points',
                arrowprops=dict(arrowstyle='-'),
            )
            map_limits.append([rx_lat, rx_lon])

        # Find the limits of the map
        min_x, min_y, max_x, max_y, zoom = self.map_utils.get_map_limits(map_limits)
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        print(f"{sub['email']}: downloading at zoomlevel {zoom}")

        cx.add_basemap(
            ax,
            zoom=zoom,  # type: ignore[arg-type]
            crs='EPSG:3857',
            source=cx.providers.OpenStreetMap.Mapnik,  # type: ignore[attr-defined]
            #source=cx.providers.CyclOSM,
            #source=cx.providers.Stamen.Terrain,
            #source=cx.providers.Stamen.TopOSMFeatures,
        )
        fig.tight_layout()

        return fig

    ####
    #### Sending email
    ####

    def get_elevation(self, lat: float, lon: float) -> Optional[float]:
        return self.retriever.get_elevation_data(lat, lon)

    def render_elevation(self, sub: pd.Series, meters: float) -> str:
        if sub['units'] == 'imperial':
            feet = meters / METERS_PER_FOOT
            return f"{round(feet):,}'"
        else:
            return f"{round(meters):,}m"

    def render_distance(self, sub: pd.Series, meters: float) -> str:
        """Render distance in brief format."""
        if sub['units'] == 'imperial':
            # If more than 1 mile, use miles; otherwise use feet
            if meters >= METERS_PER_MILE:
                miles = meters / METERS_PER_MILE
                return f"{round(miles, 1 if miles < 10 else None):,}mi"
            else:
                feet = meters / METERS_PER_FOOT
                return f"{round(feet):,}'"
        else:
            if meters >= METERS_PER_KM:
                km = meters / METERS_PER_KM
                return f"{round(km, 1 if km < 10 else None):,}km"
            else:
                return f"{round(meters):,}m"

    def get_email_text(self, sub: pd.Series, landing: pd.Series) -> tuple[str, str, str]:
        # attempt a geocode and DEM lookup
        geo = geocoder.osm(
            [landing['lat'], landing['lon']],
            method='reverse',
            headers={'User-Agent': 'jelson@gmail.com'}
        )
        elev = self.get_elevation(float(landing['lat']), float(landing['lon']))
        vel_v: Optional[float] = None
        vel_h: Optional[float] = None
        raw_vel_v = landing.get('vel_v', None)
        raw_vel_h = landing.get('vel_h', None)
        if raw_vel_v is not None and raw_vel_h is not None and not pd.isna(raw_vel_v) and not pd.isna(raw_vel_h):
            vel_v = float(raw_vel_v)
            vel_h = float(raw_vel_h)

        place = ""
        if geo and geo.county:
            if geo.town:
                place += geo.town + ", "
            if geo.city:
                place += geo.city + ", "
            place += geo.county

        # get landing time in the subscriber's timezone
        try:
            landing_localtime = landing['datetime'].tz_convert(sub['tzname'])
        except Exception:
            # If timezone conversion fails (invalid timezone), fall back to UTC
            landing_localtime = landing['datetime'].tz_convert('UTC')

        # Calculate landing estimation parameters (used in subject line and body)
        subj_lest_text: str = ""
        body_lest_text: str = ""
        if elev is not None:
            body_lest_text += f'''
                <tr>
                    <td>Ground Elev</td>
                    <td>{self.render_elevation(sub, elev)}</td>
                </tr>
            '''

            if not landing['ground_reception']:
                # If this is not a ground reception but the last-heard altitude is
                # below the ground elevation, indicate near-ground reception
                if landing['alt'] <= elev:
                    subj_lest_text += ", small radius"
                    body_lest_text += '''
                        <tr>
                            <td>Time to Landing</td>
                            <td>Near-ground reception</td>
                        </tr>
                        <tr>
                            <td>Search Radius</td>
                            <td>Small</td>
                        </tr>
                    '''
                elif vel_h is not None and vel_v is not None and vel_v <= 0:
                    time_to_landing = (landing['alt'] - elev) / -vel_v
                    horiz_error = vel_h * time_to_landing
                    subj_lest_text = f", {self.render_distance(sub, horiz_error)} radius"
                    body_lest_text += f'''
                        <tr>
                            <td>Time to landing</td>
                            <td>{round(time_to_landing)}s</td>
                        </tr>
                        <tr>
                            <td>Search Radius</td>
                            <td>{self.render_distance(sub, horiz_error)}</td>
                        </tr>
                    '''

        # subject line: "Sonde 33mi away, 2,400' radius, bearing 240° (Place Name)"
        subj = "Sonde "
        subj += self.render_distance(sub, landing['dist_from_home_m'])
        subj += " away"
        subj += subj_lest_text
        subj += f", bearing {round(landing['bearing_from_home'])}°"
        if place:
            subj += f" ({place})"
        if landing['ground_reception']:
            subj = 'GROUND RECEPTION! ' + subj

        # body
        # Handle uploaders field which may not always be present
        if 'uploaders' in landing:
            uploaders_text = ", ".join([html.escape(u['uploader_callsign']) for u in landing['uploaders']])
        else:
            uploaders_text = "unknown"

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

        serial_escaped = html.escape(landing['serial'])
        body += f'''
            <table class="sonde">
                <tr>
                    <td>Sonde ID</td>
                    <td><a href="{SONDEHUB_MAP_URL.format(serial=serial_escaped)}">{serial_escaped}</a></td>
                </tr>
                <tr>
                    <th colspan="2">Last Reception</td>
                </tr>
                <tr>
                    <td>Heard</td>
                    <td>{landing_localtime.strftime("%Y-%m-%d %H:%M:%S %Z")} by {uploaders_text}</td>
                </tr>
                <tr>
                    <td>Altitude</td>
                    <td>{self.render_elevation(sub, landing['alt'])}</td>
                </tr>
                <tr>
                    <td>Position</td>
                    <td>
                        <a href="{GMAP_URL.format(lat=landing['lat'], lon=landing['lon'])}">
                        {landing['lat']}, {landing['lon']}</a>
                    </td>
                </tr>
        '''

        if place:
            nearest_addr = html.escape(place)
            if geo and geo.address:
                nearest_addr += f'<br>{html.escape(geo.address)}'
            body += f'''
                <tr>
                    <td>Address</td>
                    <td>{nearest_addr}</td>
                </tr>
            '''

        body += f'''
            <tr>
                <td>Distance</td>
                <td>
                {self.render_distance(sub, landing['dist_from_home_m'])} from home
                (configured max:
                {self.render_distance(sub, METERS_PER_MILE * sub['max_distance_mi'])})
                </td>
            </tr>
            <tr>
                <td>Bearing</td>
                <td>{round(landing['bearing_from_home'])}° from home</td>
            </tr>
        '''

        if vel_h is not None and vel_v is not None:
            body += f'''
                <tr>
                    <td>Descent Rate</td>
                    <td>
                    {self.render_elevation(sub, -vel_v)}/s,
                    moving laterally
                    {self.render_elevation(sub, vel_h)}/s,
                    heading {round(landing['heading'])}°
                    </td>
                </tr>
            '''

        if body_lest_text:
            body += '''
                <tr>
                    <th colspan="2">Landing Estimation</th>
                </tr>
            '''
            body += body_lest_text

        unsub_url = f"https://sondesearch.lectrobox.com/notifier/unsubscribe/?uuid={sub['uuid_subscription']}"

        return subj, body, unsub_url

    def send_email(self, sub: pd.Series, landing: pd.Series) -> str:
        # Query SondeHub for detail on the flight
        flight, now = self.retriever.get_sonde_data(params={
            'duration': '1d',
            'serial': landing['serial'],
        })

        subj, body, unsub_url = self.get_email_text(sub, landing)

        # build mime message
        msg = MIMEMultipart('mixed')
        msg['Subject'] = subj
        msg['From'] = constants.FROM_EMAIL_ADDR
        msg['To'] = sub['email']
        msg['List-Unsubscribe'] = f'<{unsub_url}>'

        # Generate map filenames
        t = landing['datetime']
        map_suffix = \
            f"{sub['uuid_subscription']}/{t.year}/{t.month}/{t.day}-{t.hour}-{landing['lat']}-{landing['lon']}.jpg"
        map_url = os.path.join(EXTERNAL_IMAGES_URL) + map_suffix
        map_local_fn = os.path.join(self.args.external_images_root, map_suffix)

        # Create directory for all maps
        map_dir = os.path.split(map_local_fn)[0]
        os.makedirs(map_dir, exist_ok=True)

        ground_map_url = None
        ground_stats = None

        # If this is a ground reception, generate the ground reception map and get stats first
        if landing['ground_reception']:
            body += '''
                <tr>
                    <th colspan="2">Ground Reception</th>
                </tr>
            '''
            ground_points = map_utils.identify_ground_points(flight)
            if ground_points is not None and len(ground_points) > 0:
                # Generate filename for ground reception map
                ground_map_suffix = (
                    f"{sub['uuid_subscription']}/{t.year}/{t.month}/{t.day}-{t.hour}-"
                    f"{landing['lat']}-{landing['lon']}-ground.jpg"
                )
                ground_map_url = os.path.join(EXTERNAL_IMAGES_URL) + ground_map_suffix
                ground_map_local_fn = os.path.join(self.args.external_images_root, ground_map_suffix)

                # Generate and save the ground reception map
                print(f"{sub['email']}: generating ground reception map with {len(ground_points)} points")
                ground_fig, ground_stats = map_utils.draw_ground_reception_map(ground_points, self.map_utils, size=22)
                ground_fig.savefig(ground_map_local_fn, bbox_inches='tight')
                plt.close('all')

        # Add ground reception statistics to the table if we have them
        if ground_stats is not None:
            body += f'''
                <tr>
                    <td>Ground Points</td>
                    <td>{ground_stats.num_points} frames</td>
                </tr>
                <tr>
                    <td>Avg Position</td>
                    <td>
                        <a href="{GMAP_URL.format(lat=ground_stats.avg_lat, lon=ground_stats.avg_lon)}">
                        {ground_stats.avg_lat:.6f}, {ground_stats.avg_lon:.6f}</a>
                        (±{self.render_distance(sub, ground_stats.std_dev_combined)})
                    </td>
                </tr>
                <tr>
                    <td>Avg Altitude</td>
                    <td>
                        {self.render_elevation(sub, ground_stats.avg_alt)}
                        (±{self.render_elevation(sub, ground_stats.std_dev_alt)})
                    </td>
                </tr>
            '''
            # Add estimated AGL height if we have ground elevation
            if ground_stats.ground_elev is not None:
                height_agl = ground_stats.avg_alt - ground_stats.ground_elev
                body += f'''
                <tr>
                    <td>Est. Height</td>
                    <td>{self.render_elevation(sub, height_agl)} AGL</td>
                </tr>
            '''

        # Close the table
        body += '</table>'

        # Add footer
        body += f'''
            <p><i>
                This email was sent from the
                <a href="https://sondesearch.lectrobox.com/notifier/">Sonde Notification Service</a>.
                To unsubscribe from this notification,
                <a href="{unsub_url}">click here</a>.
                To configure your notifications,
                <a href="https://sondesearch.lectrobox.com/notifier/manage/">click here</a>.
            </i></p>
        '''

        # Generate and add the main flight map
        fig = self.get_email_image(sub, 22, flight, landing)
        fig.savefig(map_local_fn, bbox_inches='tight')
        plt.close('all')
        body += f'<p><img width="100%" src="{map_url}">'

        # Add the ground reception map if we generated one
        if ground_map_url is not None:
            body += f'<p><img width="100%" src="{ground_map_url}">'

        # all done
        body += '</body></html>'

        alternatives = MIMEMultipart('alternative')
        alternatives.attach(MIMEText(body, 'html', 'utf-8'))
        msg.attach(alternatives)

        if self.args.really_send or self.args.live_test or self.args.test_sonde:
            self.ses_client.send_raw_email(
                Source=constants.FROM_EMAIL_ADDR,
                Destinations=[constants.FROM_EMAIL_ADDR, sub['email']],
                RawMessage={
                    'Data': msg.as_string(),
                },
            )
        else:
            print(f"Subj:\n{subj}\n")
            print(f"Body:\n{body}\n")

        return map_url

    def process_one_sub(self, sondes: pd.DataFrame, now: pd.Timestamp, sub: pd.Series) -> None:
        sondes = self.annotate_with_distance(sondes, sub)

        # Sort all landings by distance-to-home
        sondes = sondes.sort_values(['dist_from_home_m'])

        # Find threshold distance in meters
        distance_threshold_m = sub['max_distance_mi'] * METERS_PER_MILE

        # Get the list of sondes that we've already sent a notification for (for
        # this subscription)
        time_sent_cutoff = Decimal(time.time() - SONDE_HISTORY_LOOKBACK_TIME_SEC)
        sondes_emailed = util.dynamodb_to_dataframe(
            self.tables.notifications.query,
            KeyConditionExpression=(
                Key('subscription_uuid').eq(sub['uuid_subscription'])
                & Key('time_sent').gt(time_sent_cutoff)
            ),
            ProjectionExpression='serial',
        )
        if sondes_emailed.empty or self.args.live_test:
            sondes_emailed = set()
        else:
            sondes_emailed = set(sondes_emailed['serial'].values)

        # Iterate over all sondes, sending notifications for any sonde that's
        # within range and for which we've not yet sent a notification
        num_emails = 0
        for _, sonde in sondes.iterrows():
            # if we've reached sondes that are beyond our desired distance, stop
            if sonde['dist_from_home_m'] > distance_threshold_m:
                break

            # if this sonde is still being tracked, do not report -- unless it's
            # a ground reception
            age = now - sonde['datetime']
            if age < pd.Timedelta(minutes=10) and not sonde['ground_reception']:
                print(f"{sub['email']}: Skipping sonde {sonde['serial']}; "
                      f"tracked {age} ago (at {sonde['datetime']}; curr time: {now})")
                continue

            if sonde['serial'] in sondes_emailed:
                print(f"{sub['email']}: Skipping sonde {sonde['serial']}; already notified")
                continue

            print(
                f"{sub['email']}: notifying for sonde {sonde['serial']}, "
                f"range {sonde['dist_from_home_m'] / METERS_PER_MILE:.1f}, "
                f"landed at {sonde['datetime'].replace(microsecond=0)}"
            )
            map_url = self.send_email(sub, sonde)
            num_emails += 1

            # Record this notification so we don't re-notify for the same sonde
            if self.args.really_send or self.args.live_test:
                self.tables.notifications.put_item(Item={
                    'subscription_uuid': sub['uuid_subscription'],
                    'time_sent': Decimal(time.time()),
                    'map_url': map_url,
                    'serial': sonde['serial'],
                    'dist_from_home_m': Decimal(round(sonde['dist_from_home_m'])),
                    'sonde_last_heard': Decimal(sonde['datetime'].timestamp()),
                })

            # Sleep after each email sent to avoid hitting various external APIs
            # too quickly
            time.sleep(1)

        print(f"{sub['email']}: Max range {sub['max_distance_mi']:.1f}mi; "
              f"nearest sonde {sondes.iloc[0]['dist_from_home_m'] / METERS_PER_MILE:.1f}mi; "
              f"sent {num_emails} emails")

    def get_subscriber_data(self) -> pd.DataFrame:
        self.tables = table_definitions.TableClients()

        # Get all user data (e.g. email addresses, units)
        users = util.dynamodb_to_dataframe(self.tables.users.scan)

        # Get all subscriptions
        subs = util.dynamodb_to_dataframe(
            self.tables.subscriptions.scan,
            FilterExpression=Attr('active').eq(True)
        )

        # If either table was empty, return nothing
        if subs.empty or users.empty:
            return pd.DataFrame()

        # Convert subscription fields to proper types
        subs = subs.astype({
            'lat': float,
            'lon': float,
            'max_distance_mi': float,
        })

        # Merge the user data into the subscription data. Each subscription
        # record has a field, "subscriber", which references the uuid field of
        # the user table.
        subs = subs.merge(
            users,
            left_on='subscriber',
            right_on='uuid',
            suffixes=('_subscription', '_user'),
        )

        # If we're in "live test" mode, filter out all notifications except for
        # a dev
        if self.args.live_test:
            subs = subs.loc[subs['email'] == DEV_EMAIL]

        return subs

    def process_test_sonde(self, sonde_id: str) -> None:
        """Test mode: send email for a specific sonde ID to dev email."""
        # Get sonde data from SondeHub for the specific sonde
        sondes, now = self.retriever.get_sonde_data(params={
            'duration': '1d',
            'serial': sonde_id,
        })

        if sondes.empty:
            print(f"Error: No data found for sonde {sonde_id}")
            return

        # Get the last frame for this sonde
        last_frame_idx = sondes['frame'].idxmax()
        landing = sondes.loc[last_frame_idx]

        # Create a mock subscription with dev email
        # Set home location 0.5 degrees away to show realistic distance/bearing
        mock_sub = pd.Series({
            'email': DEV_EMAIL,
            'lat': landing['lat'] - 0.5,
            'lon': landing['lon'] - 0.5,
            'max_distance_mi': 100.0,
            'units': 'imperial',
            'tzname': 'UTC',
            'uuid_subscription': 'test-sonde-mode',
        })

        # Annotate the landing with distance/bearing from mock home location
        sondes_df = pd.DataFrame([landing])
        sondes_df = self.annotate_with_distance(sondes_df, mock_sub)
        landing = sondes_df.iloc[0]

        print(f"Sending test email for sonde {sonde_id} to {DEV_EMAIL}")
        print(f"  Last heard: {landing['datetime']}")
        print(f"  Position: {landing['lat']}, {landing['lon']}")
        print(f"  Ground reception: {landing['ground_reception']}")
        print(f"  Distance from mock home: {landing['dist_from_home_m'] / METERS_PER_MILE:.1f} mi")

        try:
            self.send_email(mock_sub, landing)
            print("Test email sent successfully!")
        except Exception as e:
            traceback.print_exc()
            print(f"Error sending test email: {e}")

    def get_sonde_data(self) -> tuple[pd.DataFrame, pd.Timestamp]:
        # Get sonde data from SondeHub
        sondes, now = self.retriever.get_sonde_data(params={'duration': '6h'})

        # Filter the data down to just the last frame received from each sonde
        sondes = sondes.loc[sondes.groupby('serial')['frame'].idxmax()]

        return sondes, now

    def process_all_subs(self) -> None:
        # Get subscription data
        subs = self.get_subscriber_data()

        # Get sonde data
        sondes, now = self.get_sonde_data()

        for i, sub in subs.iterrows():
            try:
                self.process_one_sub(sondes, now, sub)
            except Exception as e:
                traceback.print_exc()
                print(f"Error notifying {sub['email']}: {e}")


def get_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--really-send',
        default=False,
        help='Send real notification emails to real people',
        action='store_true',
    )
    parser.add_argument(
        '--external-images-root',
        type=str,
        action='store',
        default=EXTERNAL_IMAGES_ROOT,
    )
    parser.add_argument(
        '--live-test',
        default=False,
        help='Send real email only to developers as a test',
        action='store_true',
    )
    parser.add_argument(
        '--test-sonde',
        type=str,
        help='Test mode: send email for specific sonde ID to dev email address',
    )
    args = parser.parse_args(sys.argv[1:])

    return args


def main() -> None:
    args = get_args()

    if not args.really_send and not args.live_test and not args.test_sonde:
        args.external_images_root = "./test-maps"
        if not os.path.exists(args.external_images_root):
            os.makedirs(args.external_images_root)

    if not os.path.exists(args.external_images_root):
        raise Exception(f"External images root {args.external_images_root} does not exist")

    notifier = EmailNotifier(args, util.LiveSondeHub())

    if args.test_sonde:
        # Test mode: send email for specific sonde ID
        notifier.process_test_sonde(args.test_sonde)
    else:
        # Normal mode: process all subscriptions
        notifier.process_all_subs()


if __name__ == "__main__":
    main()
