from decimal import Decimal
import cherrypy
import pytest
import requests
import os
import boto3
import json
import sys
from cryptography.fernet import Fernet

from moto import mock_secretsmanager, mock_dynamodb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import table_definitions

class Test_v1:
    @pytest.fixture
    def server(self):
        self.mock_dynamodb = mock_dynamodb()
        self.mock_dynamodb.start()
        self.mock_secretsmanager = mock_secretsmanager()
        self.mock_secretsmanager.start()

        SECRET_NAME = 'secret_name'
        os.environ['SECRET_NAME'] = SECRET_NAME
        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] ='testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

        ddb = boto3.resource('dynamodb')
        table_definitions.create_tables(ddb)
        self.sub_table = ddb.Table('sondesearch-notifier-subscriptions')
        self.pref_table = ddb.Table('sondesearch-notifier-prefs')

        sm = boto3.client('secretsmanager')
        sm.create_secret(Name=SECRET_NAME, SecretString=json.dumps({
            'fernet_key': Fernet.generate_key().decode('utf8'),
        }))

        from src import v1
        self.apiserver = v1.apiserver
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)
        yield
        cherrypy.engine.exit()
        cherrypy.engine.block()

        self.mock_dynamodb.stop()
        self.mock_secretsmanager.stop()

    def get(self, url_suffix, expected_status=200, params=None):
        url = f'http://127.0.0.1:8080/{url_suffix}'
        resp = requests.get(url, params=params)
        assert resp.status_code == expected_status
        return resp

    def post(self, url_suffix, expected_status=200, data=None):
        url = f'http://127.0.0.1:8080/{url_suffix}'
        resp = requests.post(url, data=data)
        assert resp.status_code == expected_status
        return resp
        
    def test_hello(self, server):
        resp = self.get('hello')
        assert 'hello from the sondesearch api' in resp.text

    # Ensure that for a new user, the email address returned for the
    # token corresponds to the email address we generated the token
    # for. The response shouldn't have anything else in it.
    def test_get_config_newuser(self, server):
        email = 'test@foo.bar'
        token = self.apiserver.get_signup_token(email)
        resp = self.get('get_config', params={'token': token}).json()
        assert resp['email'] == email
        resp.pop('email')
        assert resp == {}

    # Test subscribing, then unsubscribing
    def test_subscribe_unsubscribe(self, server):
        email = 'test@testme'
        token = self.apiserver.get_signup_token(email)
        resp = self.post('subscribe', data={
            'token': token,
            'lat': '77.123456789',
            'lon': '0.1',
            'max_distance_mi': '300',
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }).json()
        assert resp['email'] == email
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]
        assert sub['lat'] == 77.123456789
        assert sub['lon'] == 0.1
        assert sub['max_distance_mi'] == 300
        assert resp['prefs']['units'] == 'imperial'
        assert resp['prefs']['tzname'] == 'America/Los_Angeles'

        resp2 = self.get('get_config', params={'token': token}).json()
        assert resp == resp2

        # Unsubscribe
        self.get('unsubscribe', params={'uuid': sub['uuid']})

        resp3 = self.get('get_config', params={'token': token}).json()
        assert len(resp3['subs']) == 0

    def test_multiple_subscriptions(self, server):
        email = 'test@testme'
        token = self.apiserver.get_signup_token(email)
        templ = {
            'token': token,
            'lat': '1',
            'lon': '1',
            'max_distance_mi': '300',
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }
        resp = self.post('subscribe', data=templ).json()
        assert len(resp['subs']) == 1

        templ['lat'] = '2'
        templ['lon'] = '2'
        resp = self.post('subscribe', data=templ).json()
        assert len(resp['subs']) == 2

        templ['lat'] = '3'
        templ['lon'] = '3'
        resp = self.post('subscribe', data=templ).json()
        assert len(resp['subs']) == 3

        # unsub from 1 and 3
        for sub in resp['subs']:
            if sub['lat'] != 2:
                self.post('unsubscribe', data={'uuid': sub['uuid']})

        # make sure 2 remains
        resp = self.get('get_config', params={'token': token}).json()
        assert len(resp['subs']) == 1
        assert resp['subs'][0]['lat'] == 2
        assert resp['subs'][0]['lon'] == 2

    # Test subscribing with a missing argument
    def test_missing_subscribe(self, server):
        email = 'test@testme'
        token = self.apiserver.get_signup_token(email)
        resp = self.post('subscribe', expected_status=400, data={
            'token': token,
            'lat': 77,
            'lon': 44,
            'max_distance_mi': 300,
            'units': 'imperial',
        })
        assert 'missing arg tzname' in resp.text
