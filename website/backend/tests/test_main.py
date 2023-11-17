from decimal import Decimal
import cherrypy
import pytest
import requests
import os
import boto3
import json
import sys

from moto import mock_secretsmanager, mock_dynamodb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import table_definitions

class Test_v1:
    @pytest.fixture
    def server(self):
        self.mock_dynamodb = mock_dynamodb()
        self.mock_dynamodb.start()

        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] ='testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

        ddb = boto3.resource('dynamodb')
        table_definitions.create_tables(ddb)
        self.user_table = ddb.Table('sondesearch-notifier-users')
        self.sub_table = ddb.Table('sondesearch-notifier-subscriptions')

        from src import v1
        self.apiserver = v1.apiserver
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)
        yield
        cherrypy.engine.exit()
        cherrypy.engine.block()

        self.mock_dynamodb.stop()

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
        user_token = self.apiserver.get_user_token(email)
        resp = self.get('get_config', params={'user_token': user_token}).json()
        assert resp.pop('email') == email
        assert resp.pop('prefs') == {}
        assert resp.pop('subs') == []
        assert resp == {}

    # Test subscribing, then unsubscribing, as if we're using the
    # management portal
    def test_subscribe_unsubscribe(self, server):
        email = 'test@testme2.net'
        user_token = self.apiserver.get_user_token(email)
        resp = self.post('subscribe', data={
            'user_token': user_token,
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

        resp2 = self.get('get_config', params={'user_token': user_token}).json()
        assert resp == resp2

        # Unsubscribe
        resp3 = self.post('managed_unsubscribe', data={
            'user_token': user_token,
            'uuid': sub['uuid'],
        }).json()

        assert len(resp3['subs']) == 0
        assert resp3['email'] == email

        resp4 = self.get('get_config', params={'user_token': user_token}).json()
        assert resp3 == resp4

    def test_multiple_subscriptions(self, server):
        email = 'test@testme'
        user_token = self.apiserver.get_user_token(email)
        templ = {
            'user_token': user_token,
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
                self.post('managed_unsubscribe', data={
                    'user_token': user_token,
                    'uuid': sub['uuid']
                })

        # make sure 2 remains
        resp = self.get('get_config', params={'user_token': user_token}).json()
        assert len(resp['subs']) == 1
        assert resp['subs'][0]['lat'] == 2
        assert resp['subs'][0]['lon'] == 2

    # Test subscribing with a missing argument
    def test_missing_subscribe(self, server):
        email = 'test@testme'
        user_token = self.apiserver.get_user_token(email)
        basic_args = {
            'user_token': user_token,
            'lat': 77,
            'lon': 44,
            'max_distance_mi': 300,
            'units': 'imperial',
            'tzname': 'America',
        }

        # make sure the basic args work
        self.post('subscribe', expected_status=200, data=basic_args)

        for arg in basic_args:
            testargs = dict(basic_args)
            testargs.pop(arg)
            resp = self.post('subscribe', expected_status=400, data=testargs)
            assert f'missing argument: {arg}' in resp.text

    # Test subscribing with various arguments out of range
    def test_bad_subscribe_args(self, server):
        email = 'test@testme12.com.net'
        user_token = self.apiserver.get_user_token(email)
        basic_args = {
            'user_token': user_token,
            'lat': 77,
            'lon': 44,
            'max_distance_mi': 300,
            'units': 'imperial',
            'tzname': 'America',
        }

        tests = (
            ('lat', 100),
            ('lat', -100),
            ('lon', 190),
            ('lon', -190),
            ('units', 'foos'),
            ('max_distance_mi', -5)
        )

        self.post('subscribe', expected_status=200, data=basic_args)

        for (arg, val) in tests:
            testargs = dict(basic_args)
            testargs[arg] = val
            print(f'trying to set {arg} to {val}: {testargs}')
            resp = self.post('subscribe', expected_status=400, data=testargs)

    # Test one-click unsubscribe -- the link at the bottom of each
    # email which gives unsubscribe privileges but not full management
    # privileges
    def test_oneclick_unsubscribe(self, server):
        email = 'testnumberthree@test.com'
        lat = 23.45
        lon = -123.321
        user_token = self.apiserver.get_user_token(email)
        resp = self.post('subscribe', data={
            'user_token': user_token,
            'lat': lat,
            'lon': lon,
            'max_distance_mi': '300',
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }).json()
        assert resp['email'] == email
        assert len(resp['subs']) == 1

        sub = resp['subs'][0]

        resp2 = self.post('oneclick_unsubscribe', data={
            'uuid': sub['uuid']
        }).json()

        assert 'email' not in resp2
        assert resp2['success'] == True
        assert resp2['message'] == f'{email} will no longer get notifications for sondes near ({lat}, {lon}).'
