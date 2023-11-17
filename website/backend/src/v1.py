#!/usr/bin/env python3

import cherrypy
import datetime
import simplejson as json
import os
import sys
import time
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

EMAIL_DESTINATION = f'https://sondesearch.lectrobox.com/'

class GlobalConfig:
    def __init__(self):
        print('Global setup')
        secretsmanager = boto3.client('secretsmanager')
        self.ddb = boto3.resource('dynamodb')
        self.user_table = self.ddb.Table('sondesearch-notifier-users')
        self.sub_table = self.ddb.Table('sondesearch-notifier-subscriptions')

class ClientError(cherrypy.HTTPError):
    def __init__(self, message):
        super().__init__()
        self._msg = message.encode('utf8')

    def set_response(self):
        super().set_response()
        response = cherrypy.serving.response
        response.body = self._msg
        response.status = 400
        response.headers.pop('Content-Length', None)

class LectroboxAPI:
    PREFERENCES = ('units', 'tzname')
    VALID_UNITS = ('metric', 'imperial')

    def __init__(self, global_config):
        self._g = global_config

    @cherrypy.expose
    def hello(self):
        return f"{datetime.datetime.now()}: hello from the sondesearch api! pid {os.getpid()}"

    def get_user_token(self, email):
        # Construct the initial preferences object
        user_item = {
            'uuid': uuid.uuid4().hex,
            'email': email,
        }
        self._g.user_table.put_item(Item=user_item)
        return user_item['uuid']

    def get_user_data(self, user_token):
        rv = self._g.user_table.query(
            KeyConditionExpression=Key('uuid').eq(user_token)
        )['Items']

        if len(rv) == 0:
            raise ClientError("unknown user token")
        return rv[0]

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def send_validation_email(self, email, url):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        print(f'got validation request: e={email}, u={url}')
        user_token = self.get_user_token(email)

        # The client sends its URL to us. Replace the tail (/signup)
        # with "/manage", plus the user token.
        idx = url.index('/signup')
        next_url = url[0:idx] + f'/manage/?user_token={user_token}'
        print(next_url)

        return {'success': True}

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def get_config(self, user_token):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        user_data = self.get_user_data(user_token)

        # Get preferences
        prefs = {}
        for pref in self.PREFERENCES:
            if pref in user_data:
                prefs[pref] = user_data[pref]

        # Get subscriptions
        db_items = self._g.sub_table.query(
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
        if not arg in args:
            raise ClientError(f'missing argument: {arg}')
        if not args[arg]:
            raise ClientError(f'empty argument: {arg}')

        return args[arg]

    @cherrypy.expose
    @cherrypy.tools.json_out()
    def subscribe(self, **args):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        user_token = self._required(args, 'user_token')
        user_data = self.get_user_data(user_token)

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

        self._g.user_table.put_item(Item=user_data)
        self._g.sub_table.put_item(Item=sub_item)

        return self.get_config(user_token)

    # Generic unsubscribe. Returns both the cancelled subscription and
    # the full config after unsubscription has been processed.
    def _unsubscribe_common(self, uuid):
        # Unsubscribe
        rv = self._g.sub_table.update_item(
            Key={
                'uuid': uuid,
            },
            UpdateExpression='SET active=:f',
            ExpressionAttributeValues={
                ':f': False,
            },
            ReturnValues="ALL_NEW",
        )
        sub = rv['Attributes']

        return {
            'cancelled_sub': sub,
            'config': self.get_config(sub['subscriber']),
        }

    # Unsubscribe link put at the bottom of each email - no user token
    # available or required, so no data is returned, no management
    # possible.
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def oneclick_unsubscribe(self, uuid):
        res = self._unsubscribe_common(uuid)
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'
        return {
            'success': True,
            'message': '{} will no longer get notifications for sondes near ({}, {}).'.format(
                res['config']['email'],
                res['cancelled_sub']['lat'],
                res['cancelled_sub']['lon'],
            ),
        }

    # Management portal unsubscribe where a user token is provided. If
    # the user token is valid, the new config is returned after the
    # unsubscribe is processed. This prevents the portal from needing
    # a second RTT to get the new config.
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def managed_unsubscribe(self, user_token, uuid):
        res = self._unsubscribe_common(uuid)

        if res['cancelled_sub']['subscriber'] != user_token:
            raise ClientError('user token does not match subscriber of uuid')

        return res['config']

#def main():
#    cherrypy.quickstart(LectroboxAPI())

global_config = GlobalConfig()
apiserver = LectroboxAPI(global_config)
cherrypy.tree.mount(apiserver)

# "application" is the magic function called by Apache's wsgi module
def application(environ, start_response):
    cherrypy.config.update({
        'log.screen': True,
        'environment': 'production',
    })
    return cherrypy.tree(environ, start_response)
