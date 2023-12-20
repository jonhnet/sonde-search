#!/usr/bin/env python3

from decimal import Decimal
import boto3
import cherrypy
import datetime
import os
import sys
import time
import uuid

from boto3.dynamodb.conditions import Key, Attr

sys.path.insert(0, os.path.dirname(__file__))
import constants
import table_definitions

EMAIL_DESTINATION = 'https://sondesearch.lectrobox.com/'


class GlobalConfig:
    def __init__(self):
        print('Global setup')
        table_definitions.create_table_clients(self)


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
    VERIFY_EMAIL_SUBJ = 'Verify your email to receive sonde notifications'

    def __init__(self, global_config):
        self._g = global_config

    @cherrypy.expose
    def hello(self):
        return f"{datetime.datetime.now()}: hello from the sondesearch api! pid {os.getpid()}"

    def get_time(self):
        return Decimal(time.time())

    def get_user_token(self, email):
        # Check to see if this email already exists in the system. If
        # so, simply return the existing UUID.
        rv = self._g.user_table.query(
            IndexName='email-index',
            KeyConditionExpression=Key('email').eq(email)
        )['Items']
        if len(rv) > 0:
            return rv[0]['uuid']

        # Email address does not exist yet. Construct the initial
        # preferences object and insert it.
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
        if arg not in args:
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

        self._g.user_table.put_item(Item=user_data)
        self._g.sub_table.put_item(Item=sub_item)

        # Editing an entry is actually a combination subscribe + unsubscribe.
        # Edits set the 'replace_uuid' property to indicate which subscription
        # should be cancelled one this one is successfully created.
        if 'replace_uuid' in args:
            self._unsubscribe_common(args['replace_uuid'])

        return self.get_config(user_token)

    # Generic unsubscribe. Returns both the cancelled subscription and
    # the full config after unsubscription has been processed.
    def _unsubscribe_common(self, uuid):
        # Unsubscribe
        rv = self._g.sub_table.update_item(
            Key={
                'uuid': uuid,
            },
            UpdateExpression='SET active=:f, unsubscribe_time=:now',
            ExpressionAttributeValues={
                ':f': False,
                ':now': self.get_time(),
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
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        res = self._unsubscribe_common(uuid)
        return {
            'success': True,
            'email': res['config']['email'],
            'cancelled_sub_lat': res['cancelled_sub']['lat'],
            'cancelled_sub_lon': res['cancelled_sub']['lon'],
        }

    # Management portal unsubscribe where a user token is provided. If
    # the user token is valid, the new config is returned after the
    # unsubscribe is processed. This prevents the portal from needing
    # a second RTT to get the new config.
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def managed_unsubscribe(self, user_token, uuid):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        res = self._unsubscribe_common(uuid)

        if res['cancelled_sub']['subscriber'] != user_token:
            raise ClientError('user token does not match subscriber of uuid')

        return res['config']

# This is called both by the uwsgi path, via application(), and the unit test
def mount_server_instance():
    global_config = GlobalConfig()
    apiserver = LectroboxAPI(global_config)
    cherrypy.tree.mount(apiserver)
    return apiserver

# "application" is the magic function called by Apache's wsgi module
def application(environ, start_response):
    mount_server_instance()
    cherrypy.config.update({
        'log.screen': True,
        'environment': 'production',
    })
    return cherrypy.tree(environ, start_response)
