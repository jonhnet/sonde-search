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
    def send_validation_email(self, email, url):
        print(f'got request: e={email}, u={url}')
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'
        token = self.get_signup_token(email)
        idx = url.index('/signup')
        next_url = url[0:idx] + f'/manage/?token={token}'
        return 'hello'

    PREFERENCES = ('units', 'tzname')

    @cherrypy.expose
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
        return json.dumps(resp, indent=2)

    def _required(self, args, arg):
        if not arg in args:
            raise ClientError(f'missing arg {arg}')
        return args[arg]

    @cherrypy.expose
    def subscribe(self, **args):
        user_token = self._required(args, 'user_token')
        user_data = self.get_user_data(user_token)

        # Construct the preferences object
        user_data.update({
            'units': self._required(args, 'units'),
            'tzname': self._required(args, 'tzname'),
        })
        self._g.user_table.put_item(Item=user_data)

        # Construct the subscription object
        sub_item = {
            'uuid': uuid.uuid4().hex,
            'subscriber': user_data['uuid'],
            'active': True,
            'lat': Decimal(self._required(args, 'lat')),
            'lon': Decimal(self._required(args, 'lon')),
            'max_distance_mi': Decimal(self._required(args, 'max_distance_mi')),
        }
        self._g.sub_table.put_item(Item=sub_item)

        return self.get_config(user_token)

    @cherrypy.expose
    def unsubscribe(self, uuid):
        self._g.sub_table.update_item(
            Key={
                'uuid': uuid,
            },
            UpdateExpression='SET active=:f',
            ExpressionAttributeValues={
                ':f': False,
            }
        )

        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

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
