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

from cryptography.fernet import Fernet

EMAIL_DESTINATION = f'https://sondesearch.lectrobox.com/'

class GlobalConfig:
    def __init__(self):
        print('Global setup')
        secretsmanager = boto3.client('secretsmanager')
        self.secrets = json.loads(secretsmanager.get_secret_value(SecretId=os.environ['SECRET_NAME'])['SecretString'])
        self.encryptor = Fernet(self.secrets['fernet_key'])
        self.ddb = boto3.resource('dynamodb')
        self.sub_table = self.ddb.Table('sondesearch-notifier-subscriptions')
        self.pref_table = self.ddb.Table('sondesearch-notifier-prefs')

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

    def _client_error(self, message):
        cherrypy.response.status = 400
        cherrypy.response.body = message.encode('utf8')
        raise cherrypy.CherryPyException

    @cherrypy.expose
    def hello(self):
        return f"{datetime.datetime.now()}: hello from the sondesearch api! pid {os.getpid()}"

    def get_email(self, token):
        email = json.loads(self._g.encryptor.decrypt(token.encode('utf8')))['e']
        print(f'got request for {email}')
        return email

    def get_signup_token(self, email):
        token_data = {
            'e': email,
        }
        return self._g.encryptor.encrypt(json.dumps(token_data).encode('utf8')).decode('utf8')
        
    @cherrypy.expose
    def send_validation_email(self, email, url):
        print(f'got request: e={email}, u={url}')
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'
        token = self.get_signup_token(email)
        idx = url.index('/signup')
        next_url = url[0:idx] + f'/manage/?token={token}'
        return 'hello'

    @cherrypy.expose
    def get_config(self, token):
        cherrypy.response.headers['Access-Control-Allow-Origin'] = '*'

        email = self.get_email(token)
        prefs = self._g.pref_table.query(
            KeyConditionExpression=Key('email').eq(email)
        )['Items']

        # Check to see if this user has any preferences stored
        if len(prefs) == 0:
            return json.dumps({
                'email': email,
            })

        prefs = prefs[0]

        # Get subscriptions
        db_items = self._g.sub_table.query(
            IndexName='email-index',
            KeyConditionExpression=Key('email').eq(email),
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
            'email': email,
            'prefs': {
                'units': prefs['units'],
                'tzname': prefs['tzname'],
            },
            'subs': subs,
        }
        return json.dumps(resp, indent=2)

    def _required(self, args, arg):
        if not arg in args:
            raise ClientError(f'missing arg {arg}')
        return args[arg]

    @cherrypy.expose
    def subscribe(self, **args):
        token = self._required(args, 'token')
        email = self.get_email(token)

        # Construct the preferences object
        pref_item = {
            'email': email,
            'units': self._required(args, 'units'),
            'tzname': self._required(args, 'tzname'),
        }            
        self._g.pref_table.put_item(Item=pref_item)

        # Construct the subscription object
        ddb_item = {
            'uuid': uuid.uuid4().hex,
            'email': email,
            'active': True,
            'lat': Decimal(self._required(args, 'lat')),
            'lon': Decimal(self._required(args, 'lon')),
            'max_distance_mi': Decimal(self._required(args, 'max_distance_mi')),
        }
        self._g.sub_table.put_item(Item=ddb_item)

        return self.get_config(token)

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
