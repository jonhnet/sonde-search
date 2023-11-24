import cherrypy
import pytest
import requests
import os
import boto3
import sys

from moto import mock_dynamodb, mock_ses

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import table_definitions


class Test_v1:
    @pytest.fixture
    def server(self):
        self.mock_dynamodb = mock_dynamodb()
        self.mock_dynamodb.start()
        self.mock_ses = mock_ses()
        self.mock_ses.start()

        os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
        os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
        os.environ['AWS_SECURITY_TOKEN'] = 'testing'
        os.environ['AWS_SESSION_TOKEN'] = 'testing'
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

        ddb = boto3.resource('dynamodb')
        table_definitions.create_tables(ddb)
        self.user_table = ddb.Table('sondesearch-notifier-users')
        self.sub_table = ddb.Table('sondesearch-notifier-subscriptions')

        from src import v1

        ses = boto3.client('ses')
        ses.verify_email_address(EmailAddress=v1.LectroboxAPI.FROM_EMAIL_ADDR)

        self.apiserver = v1.apiserver
        cherrypy.engine.start()
        cherrypy.engine.wait(cherrypy.engine.states.STARTED)
        yield
        cherrypy.engine.exit()
        cherrypy.engine.block()

        self.mock_dynamodb.stop()
        self.mock_ses.stop()

    def sub_args(self, user_token):
        return {
            'user_token': user_token,
            'lat': '77.123456789',
            'lon': '0.1',
            'max_distance_mi': '300',
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }

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

    # Test sending a notification email
    def test_send_validation_email(self, server):
        email = 'jelson@gmail.com'
        self.post('send_validation_email', data={
            'email': email,
            'url': 'https://sondesearch.lectrobox.com/notifier/signup',
        })

    # Test subscribing, then unsubscribing, as if we're using the
    # management portal
    def test_subscribe_unsubscribe(self, server):
        email = 'test@testme2.net'
        user_token = self.apiserver.get_user_token(email)
        test_sub = self.sub_args(user_token)
        resp = self.post('subscribe', data=test_sub).json()
        assert resp['email'] == email
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]
        assert sub['lat'] == float(test_sub['lat'])
        assert sub['lon'] == float(test_sub['lon'])
        assert sub['max_distance_mi'] == float(test_sub['max_distance_mi'])
        assert resp['prefs']['units'] == test_sub['units']
        assert resp['prefs']['tzname'] == test_sub['tzname']

        # Get config and ensure we get the same config block back again
        resp2 = self.get('get_config', params={'user_token': user_token}).json()
        assert resp == resp2

        # Unsubscribe
        resp3 = self.post('managed_unsubscribe', data={
            'user_token': user_token,
            'uuid': sub['uuid'],
        }).json()

        assert len(resp3['subs']) == 0
        assert resp3['email'] == email

        # Get config again, ensure it's the same as the unsubscribe response
        resp4 = self.get('get_config', params={'user_token': user_token}).json()
        assert resp3 == resp4

    # Test making a subscription, then losing your credentials and
    # asking for another auth link to be emailed. Your subscription
    # state should be retained.
    def test_lost_credentials(self, server):
        email = 'lost-credentials@test.net'
        user_token = self.apiserver.get_user_token(email)
        resp = self.post('subscribe', data=self.sub_args(user_token)).json()
        assert resp['email'] == email
        assert len(resp['subs']) == 1

        # ask for new credentials and make sure the sub is still there
        user_token2 = self.apiserver.get_user_token(email)

        resp2 = self.get('get_config', params={'user_token': user_token2}).json()
        assert resp == resp2

    def test_multiple_subscriptions(self, server):
        email = 'test@testme'
        user_token = self.apiserver.get_user_token(email)
        templ = self.sub_args(user_token)
        templ['lat'] = '1'
        templ['lon'] = '1'
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
        basic_args = self.sub_args(user_token)

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
        basic_args = self.sub_args(user_token)

        tests = (
            ('lat', '90.1'),
            ('lat', '-90.1'),
            ('lon', '180.1'),
            ('lon', '-180.1'),
            ('units', 'foos'),
            ('max_distance_mi', '-5'),
            ('max_distance_mi', '-0.001'),
        )

        self.post('subscribe', expected_status=200, data=basic_args)

        for (arg, val) in tests:
            testargs = dict(basic_args)
            testargs[arg] = val
            print(f'trying to set {arg} to {val}: {testargs}')
            self.post('subscribe', expected_status=400, data=testargs)

    # Test one-click unsubscribe -- the link at the bottom of each
    # email which gives unsubscribe privileges but not full management
    # privileges
    def test_oneclick_unsubscribe(self, server):
        email = 'testnumberthree@test.com'
        user_token = self.apiserver.get_user_token(email)

        # first subscription
        sub1 = self.sub_args(user_token)
        sub1['lat'] = 23.45
        sub1['lon'] = -123.321
        resp1 = self.post('subscribe', data=sub1).json()
        assert resp1['email'] == email
        assert len(resp1['subs']) == 1

        # second subscription
        sub2 = self.sub_args(user_token)
        sub2['lat'] = 11.11
        sub2['lon'] = 22.22
        resp2 = self.post('subscribe', data=sub2).json()
        assert resp2['email'] == email
        assert len(resp2['subs']) == 2

        # make sure there are two subscriptons returned from get_config
        resp3 = self.get('get_config', params={'user_token': user_token}).json()
        assert len(resp3['subs']) == 2

        # unsubscribe from sub1 using the uuid-only API
        resp4 = self.post('oneclick_unsubscribe', data={
            'uuid': resp1['subs'][0]['uuid']
        }).json()
        # make sure no personal data is returned from this API
        assert resp4.pop('success') is True
        assert resp4.pop('message') == f'{email} will no longer get notifications for sondes near ({sub1["lat"]}, {sub1["lon"]}).'
        assert resp4 == {}

        # use the authorized-user management api to get the config;
        # make sure sub1 is gone and sub2 is still there
        resp5 = self.get('get_config', params={'user_token': user_token}).json()
        assert resp5['email'] == email
        assert len(resp5['subs']) == 1
        assert resp5['subs'][0]['lat'] == sub2['lat']
        assert resp5['subs'][0]['lon'] == sub2['lon']

    # Make sure we keep two accounts straight
    def test_two_accounts(self, server):
        # user 1
        email1 = 'testuser_1@test.com'
        user_token1 = self.apiserver.get_user_token(email1)
        sub1 = self.sub_args(user_token1)
        sub1['max_distance_mi'] = 111
        self.post('subscribe', data=sub1).json()

        # user 2
        email2 = 'testuser_2@test.com'
        user_token2 = self.apiserver.get_user_token(email2)
        sub2 = self.sub_args(user_token2)
        sub2['max_distance_mi'] = 222
        self.post('subscribe', data=sub2).json()

        # verify user 1
        resp1 = self.get('get_config', params={'user_token': user_token1}).json()
        assert resp1['email'] == email1
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 111

        # verify user 2
        resp1 = self.get('get_config', params={'user_token': user_token2}).json()
        assert resp1['email'] == email2
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 222
