#!/usr/bin/env python3

from decimal import Decimal
import boto3
import cherrypy
import datetime
import os
import pandas as pd
import simplekml
import sys
import time
import uuid

from boto3.dynamodb.conditions import Key, Attr

sys.path.insert(0, os.path.dirname(__file__))
import constants
import table_definitions
import util

EMAIL_DESTINATION = 'https://sondesearch.lectrobox.com/'

# A placeholder for expensive setup that should only be done once. This
# iteration of the program no longer has any such setup so this now has nothing
# in it.
class GlobalConfig:
    def __init__(self, retriever):
        print('Global setup')
        self.retriever = retriever


class ClientError(cherrypy.HTTPError):
    def __init__(self, message):
        super().__init__()
        print(f"client error: {message}")
        self._msg = message.encode('utf8')

    def set_response(self):
        super().set_response()
        response = cherrypy.serving.response
        response.body = self._msg
        response.status = 400
        response.headers.pop('Content-Length', None)


def allow_lectrobox_cors(func):
    def wrapper(*args, **kwargs):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = 'https://sondesearch.lectrobox.com'
        cherrypy.response.headers['Access-Control-Allow-Credentials'] = 'true'
        return func(*args, **kwargs)

    return wrapper

class SondesearchAPI:
    PREFERENCES = ('units', 'tzname')
    VALID_UNITS = ('metric', 'imperial')
    VERIFY_EMAIL_SUBJ = 'Verify your email to receive sonde notifications'

    def __init__(self, global_config: GlobalConfig):
        self._g = global_config
        self.tables = table_definitions.TableClients()

    @cherrypy.expose
    def hello(self):
        return f"{datetime.datetime.now()}: hello from the v2 sondesearch api! pid {os.getpid()}"

    def get_time(self):
        return Decimal(time.time())

    def get_user_token_from_email(self, email):
        # Check to see if this email already exists in the system. If
        # so, simply return the existing UUID.
        rv = self.tables.users.query(
            IndexName='email-lc-index',
            KeyConditionExpression=Key('email_lc').eq(email.lower())
        )['Items']
        if len(rv) > 0:
            return rv[0]['uuid']

        # Email address does not exist yet. Construct the initial
        # preferences object and insert it.
        user_item = {
            'uuid': uuid.uuid4().hex,
            'email': email,
            'email_lc': email.lower(),
        }
        print(f"creating new user, uuid {user_item['uuid']}")
        self.tables.users.put_item(Item=user_item)
        return user_item['uuid']

    def get_user_token_from_request(self):
        if 'notifier_user_token_v2' not in cherrypy.request.cookie:
            raise ClientError("no user token in request cookies")

        return cherrypy.request.cookie['notifier_user_token_v2'].value

    def get_user_data(self):
        user_token = self.get_user_token_from_request()
        rv = self.tables.users.query(
            KeyConditionExpression=Key('uuid').eq(user_token)
        )['Items']

        if len(rv) == 0:
            raise ClientError(f"unknown user token {user_token}")
        assert len(rv) == 1
        rv = rv[0]
        print(f"Got user data for uuid {rv['uuid']}, email {rv['email']}")
        return rv

    @cherrypy.expose
    @cherrypy.tools.json_out()
    @allow_lectrobox_cors
    def send_validation_email(self, email, url):
        print(f'got validation request: e={email}, u={url}')
        user_token = self.get_user_token_from_email(email)

        # The client sends its URL to us. Replace the tail (/signup)
        # with "/manage", plus the user token.
        idx = url.index('/signup')
        next_url = url[0:idx] + f'/verify/?user_token={user_token}'
        print(f'got signup request from {email}: sending to {next_url}')

        # construct the email body
        with open(os.path.join(os.path.dirname(__file__), "../config/verification-template.txt")) as f:
            body_template = f.read()
        body = body_template.format(EMAIL=email, URL=next_url)

        # send
        ses = boto3.client('ses')
        ses.send_email(
            Source=constants.FROM_EMAIL_ADDR,
            Destination={
                'ToAddresses': [email],
                'BccAddresses': [constants.FROM_EMAIL_ADDR],
            },
            Message={
                'Subject': {
                    'Data': self.VERIFY_EMAIL_SUBJ,
                    'Charset': 'utf-8',
                },
                'Body': {
                    'Html': {
                        'Data': body,
                        'Charset': 'utf-8',
                    },
                },
            },
        )

        return {'success': True}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    @allow_lectrobox_cors
    def get_config(self):
        user_data = self.get_user_data()

        # Get preferences
        prefs = {}
        for pref in self.PREFERENCES:
            if pref in user_data:
                prefs[pref] = user_data[pref]

        # Get subscriptions
        db_items = self.tables.subscriptions.query(
            IndexName='subscriber-index',
            KeyConditionExpression=Key('subscriber').eq(user_data['uuid']),
            FilterExpression=Attr('active').eq(True),
        )

        subs = []
        for item in db_items['Items']:
            subs.append({
                'uuid': item['uuid'],
                'lat': item['lat'],
                'lon': item['lon'],
                'max_distance_mi': item['max_distance_mi'],
            })

        # Return both preferences and subscriptions
        resp = {
            'email': user_data['email'],
            'prefs': prefs,
            'subs': subs,
        }

        return resp

    def _required(self, args, arg):
        if arg not in args:
            raise ClientError(f'missing argument: {arg}')
        if not args[arg]:
            raise ClientError(f'empty argument: {arg}')

        return args[arg]

    @cherrypy.expose
    @cherrypy.tools.json_out()
    @allow_lectrobox_cors
    def subscribe(self, **args):
        user_data = self.get_user_data()

        # Construct the preferences object
        user_data.update({
            'units': self._required(args, 'units'),
            'tzname': self._required(args, 'tzname'),
        })

        # Construct the subscription object
        sub_item = {
            # uuid of the subscription
            'uuid': uuid.uuid4().hex,

            # uuid of the subscriber
            'subscriber': user_data['uuid'],

            'active': True,
            'subscribe_time': self.get_time(),
            'lat': Decimal(self._required(args, 'lat')),
            'lon': Decimal(self._required(args, 'lon')),
            'max_distance_mi': Decimal(self._required(args, 'max_distance_mi')),
        }

        if not user_data['units'] in self.VALID_UNITS:
            raise ClientError(f'invalid unit {user_data["units"]}')
        if not -90 <= sub_item['lat'] <= 90:
            raise ClientError('latitude out of range')
        if not -180 <= sub_item['lon'] <= 180:
            raise ClientError('longitude out of range')
        if sub_item['max_distance_mi'] <= 0:
            raise ClientError('max_distance_mi must be positive')

        print(f"subscriber {sub_item['subscriber']}: new subscription {sub_item['uuid']}")

        self.tables.users.put_item(Item=user_data)
        self.tables.subscriptions.put_item(Item=sub_item)

        # Editing an entry is actually a combination subscribe + unsubscribe.
        # Edits set the 'replace_uuid' property to indicate which subscription
        # should be cancelled one this one is successfully created.
        if 'replace_uuid' in args:
            print(f"deleting old subscription {args['replace_uuid']}")
            self._unsubscribe_common(args['replace_uuid'])

        return self.get_config()

    # Generic unsubscribe. Returns both the cancelled subscription and
    # the full config after unsubscription has been processed.
    # If optional user token is given, ensure it matches.
    def _unsubscribe_common(self, uuid, user_token=None):
        # Unsubscribe
        args = {
            'Key': {
                'uuid': uuid,
            },
            'UpdateExpression': 'SET active=:f, unsubscribe_time=:now',
            'ExpressionAttributeValues': {
                ':f': False,
                ':now': self.get_time(),
            },
            'ReturnValues': "ALL_NEW",
        }

        if user_token is not None:
            args['ConditionExpression'] = Key('subscriber').eq(user_token)

        rv = self.tables.subscriptions.update_item(**args)
        sub = rv['Attributes']

        return {
            'cancelled_sub': sub,
        }

    # Unsubscribe link put at the bottom of each email - no user token
    # available or required, so no data is returned, no management
    # possible.
    @cherrypy.expose
    @cherrypy.tools.json_out()
    @allow_lectrobox_cors
    def oneclick_unsubscribe(self, uuid):
        res = self._unsubscribe_common(uuid)
        print(f"one-click unsubscribe of subscription {uuid}")
        return {
            'success': True,
            'cancelled_sub_lat': res['cancelled_sub']['lat'],
            'cancelled_sub_lon': res['cancelled_sub']['lon'],
        }

    # Management portal unsubscribe where a user token is provided. If
    # the user token is valid, the new config is returned after the
    # unsubscribe is processed. This prevents the portal from needing
    # a second RTT to get the new config.
    @cherrypy.expose
    @cherrypy.tools.json_out()
    @allow_lectrobox_cors
    def managed_unsubscribe(self, uuid):
        user_token = self.get_user_token_from_request()
        print(f"subscriber {user_token} unsubscribing from subscription {uuid}")
        self._unsubscribe_common(uuid, user_token=user_token)
        return self.get_config()

    @cherrypy.expose
    @allow_lectrobox_cors
    def get_notification_history(self):
        cherrypy.response.headers['Content-Type'] = 'application/json'

        NUM_HISTORY_DAYS = 31
        time_sent_cutoff = Decimal(time.time() - NUM_HISTORY_DAYS * 86400)

        # Get the user token
        user_token = self.get_user_token_from_request()

        # First, get all of this user's subscriptions
        subs = util.dynamodb_to_dataframe(
            self.tables.subscriptions.query,
            IndexName='subscriber-index',
            KeyConditionExpression=Key('subscriber').eq(user_token),
        )

        if subs.empty:
            # If there are no subscriptions, return nothing
            rv = '[]'
        else:
            # Get notification history for each subscription
            dfs = []
            for sub in subs['uuid']:
                dfs.append(util.dynamodb_to_dataframe(
                    self.tables.notifications.query,
                    KeyConditionExpression=Key('subscription_uuid').eq(sub) &
                    Key('time_sent').gt(time_sent_cutoff),
                ))
            notifications = pd.concat(dfs)
            rv = notifications.to_json(orient='records')

        return rv.encode('utf-8')

    @cherrypy.expose
    def get_sonde_kml(self, serial):
        sonde, now = self._g.retriever.get_sonde_data(params={
            'serial': serial,
        })

        if sonde.empty:
            return f"Sorry, it seems that sonde {serial} does not exist."

        # Index by datetime and drop all columns other than lat, lon, alt
        sonde = sonde.set_index('datetime')[['lon', 'lat', 'alt']]

        # For each minute, take the last location a sonde was seen during that
        # minute. Also add the very first sonde sighting, and the highest
        # altitude point. Note for the highest point we take head(1) in case
        # there are multiple reports at that highest altitude. We pass a list
        # to sonde.loc[] to ensure we get a dataframe back from loc, not a series,
        # in case the label is uinque.
        by_minute = pd.concat([
            sonde.head(1),
            sonde.resample('1 min', label='right').last(),
            sonde.loc[[sonde['alt'].idxmax()]].head(1),
        ]).dropna().sort_index()

        # Create KML document
        kml = simplekml.Kml()
        kml.document.name = serial
        linestring = kml.newlinestring(name=serial)
        linestring.coords = list(by_minute.itertuples(index=False, name=None))
        linestring.altitudemode = simplekml.AltitudeMode.absolute
        linestring.extrude = 1
        linestring.style.linestyle.color = simplekml.Color.red
        linestring.style.linestyle.width = 5

        cherrypy.response.headers['Content-Type'] = 'application/vnd.google-earth.kml+xml'
        cherrypy.response.headers['Content-Disposition'] = f'attachment; filename="{serial}.kml"'
        return kml.kml().encode('utf8')

global_config = None

# This is called both by the uwsgi path, via application(), and the unit test
def mount_server_instance(retriever):
    global global_config
    if not global_config:
        global_config = GlobalConfig(retriever=retriever)

    apiserver = SondesearchAPI(global_config)
    cherrypy.tree.mount(apiserver)
    return apiserver

# "application" is the magic function called by Apache's wsgi module or uwsgi
def application(environ, start_response):
    mount_server_instance(retriever=util.LiveSondeHub())
    cherrypy.config.update({
        'log.screen': True,
        'environment': 'production',
        'tools.proxy.on': True,
    })
    return cherrypy.tree(environ, start_response)

# For local testing
if __name__ == "__main__":
    cherrypy.config.update({
        'log.screen': True,
    })
    cherrypy.server.socket_host = '::'
    cherrypy.quickstart(mount_server_instance(retriever=util.LiveSondeHub()), '/')
