import argparse
import base64
import boto3
import bz2
import cherrypy
import email
import json
import os
import pytest
import re
import requests
import sys

from moto import mock_dynamodb, mock_ses
from moto.core import DEFAULT_ACCOUNT_ID
from moto.ses import ses_backends

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import v1, send_sonde_email, table_definitions, constants

@pytest.fixture
def mock_aws(request):
    _mock_dynamodb = mock_dynamodb()
    _mock_dynamodb.start()
    _mock_ses = mock_ses()
    _mock_ses.start()

    os.environ['AWS_ACCESS_KEY_ID'] = 'testing'
    os.environ['AWS_SECRET_ACCESS_KEY'] = 'testing'
    os.environ['AWS_SECURITY_TOKEN'] = 'testing'
    os.environ['AWS_SESSION_TOKEN'] = 'testing'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

    table_definitions.create_tables()

    ses = boto3.client('ses')
    ses.verify_email_address(EmailAddress=constants.FROM_EMAIL_ADDR)
    request.cls.ses_backend = ses_backends[DEFAULT_ACCOUNT_ID]['us-east-1']

    yield

    _mock_dynamodb.stop()
    _mock_ses.stop()

# general strategy for doing unit tests with cherrypy cribbed from:
#   https://schneide.blog/2017/02/06/integration-tests-with-cherrypy-and-requests/
@pytest.fixture
def server(request, mock_aws):
    request.cls.apiserver = v1.mount_server_instance()
    cherrypy.config.update({
        'request.throw_errors': True,
    })
    cherrypy.engine.start()
    cherrypy.engine.wait(cherrypy.engine.states.STARTED)
    yield
    cherrypy.engine.exit()
    cherrypy.engine.block()

def get(url_suffix, expected_status=200, params=None):
    url = f'http://127.0.0.1:8080/{url_suffix}'
    resp = requests.get(url, params=params)
    assert resp.status_code == expected_status
    return resp

def post(url_suffix, expected_status=200, data=None):
    url = f'http://127.0.0.1:8080/{url_suffix}'
    resp = requests.post(url, data=data)
    assert resp.status_code == expected_status
    return resp

@pytest.mark.usefixtures("server")
class Test_v1:

    def sub_args(self, user_token):
        return {
            'user_token': user_token,
            'lat': '77.123456789',
            'lon': '0.1',
            'max_distance_mi': '300',
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }

    def test_hello(self):
        resp = get('hello')
        assert 'hello from the sondesearch api' in resp.text

    # Ensure that for a new user, the email address returned for the
    # token corresponds to the email address we generated the token
    # for. The response shouldn't have anything else in it.
    def test_get_config_newuser(self):
        addr = 'test@foo.bar'
        user_token = self.apiserver.get_user_token(addr)
        resp = get('get_config', params={'user_token': user_token}).json()
        assert resp.pop('email') == addr
        assert resp.pop('prefs') == {}
        assert resp.pop('subs') == []
        assert resp == {}

    # Test sending a notification email
    def test_send_validation_email(self):
        addr = 'jelson@gmail.com'
        post('send_validation_email', data={
            'email': addr,
            'url': 'https://sondesearch.lectrobox.com/notifier/signup',
        })
        sent_emails = self.ses_backend.sent_messages
        assert len(sent_emails) == 1
        sent_email = sent_emails[0]
        assert 1 == len(sent_email.destinations['ToAddresses'])
        assert addr == sent_email.destinations['ToAddresses'][0]
        assert 'Hello!' in sent_email.body
        mo = re.search('user_token=([a-z0-9]+)', sent_email.body)
        assert mo is not None
        user_token = self.apiserver.get_user_token(addr)
        assert mo.group(1) == user_token

    # Test subscribing, then unsubscribing, as if we're using the
    # management portal
    def test_subscribe_unsubscribe(self):
        addr = 'test@testme2.net'
        user_token = self.apiserver.get_user_token(addr)
        test_sub = self.sub_args(user_token)
        resp = post('subscribe', data=test_sub).json()
        assert resp['email'] == addr
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]
        assert sub['lat'] == float(test_sub['lat'])
        assert sub['lon'] == float(test_sub['lon'])
        assert sub['max_distance_mi'] == float(test_sub['max_distance_mi'])
        assert resp['prefs']['units'] == test_sub['units']
        assert resp['prefs']['tzname'] == test_sub['tzname']

        # Get config and ensure we get the same config block back again
        resp2 = get('get_config', params={'user_token': user_token}).json()
        assert resp == resp2

        # Unsubscribe
        resp3 = post('managed_unsubscribe', data={
            'user_token': user_token,
            'uuid': sub['uuid'],
        }).json()

        assert len(resp3['subs']) == 0
        assert resp3['email'] == addr

        # Get config again, ensure it's the same as the unsubscribe response
        resp4 = get('get_config', params={'user_token': user_token}).json()
        assert resp3 == resp4

    # Test making a subscription, then losing your credentials and
    # asking for another auth link to be emailed. Your subscription
    # state should be retained.
    def test_lost_credentials(self, server):
        addr = 'lost-credentials@test.net'
        user_token = self.apiserver.get_user_token(addr)
        resp = post('subscribe', data=self.sub_args(user_token)).json()
        assert resp['email'] == addr
        assert len(resp['subs']) == 1

        # ask for new credentials and make sure the sub is still there
        user_token2 = self.apiserver.get_user_token(addr)

        resp2 = get('get_config', params={'user_token': user_token2}).json()
        assert resp == resp2

    def test_multiple_subscriptions(self, server):
        addr = 'test@testme'
        user_token = self.apiserver.get_user_token(addr)
        templ = self.sub_args(user_token)
        templ['lat'] = '1'
        templ['lon'] = '1'
        resp = post('subscribe', data=templ).json()
        assert len(resp['subs']) == 1

        templ['lat'] = '2'
        templ['lon'] = '2'
        resp = post('subscribe', data=templ).json()
        assert len(resp['subs']) == 2

        templ['lat'] = '3'
        templ['lon'] = '3'
        resp = post('subscribe', data=templ).json()
        assert len(resp['subs']) == 3

        # unsub from 1 and 3
        for sub in resp['subs']:
            if sub['lat'] != 2:
                post('managed_unsubscribe', data={
                    'user_token': user_token,
                    'uuid': sub['uuid']
                })

        # make sure 2 remains
        resp = get('get_config', params={'user_token': user_token}).json()
        assert len(resp['subs']) == 1
        assert resp['subs'][0]['lat'] == 2
        assert resp['subs'][0]['lon'] == 2

    # Test subscribing with a missing argument
    def test_missing_subscribe(self, server):
        addr = 'test@testme'
        user_token = self.apiserver.get_user_token(addr)
        basic_args = self.sub_args(user_token)

        # make sure the basic args work
        post('subscribe', expected_status=200, data=basic_args)

        for arg in basic_args:
            testargs = dict(basic_args)
            testargs.pop(arg)
            resp = post('subscribe', expected_status=400, data=testargs)
            assert f'missing argument: {arg}' in resp.text

    # Test subscribing with various arguments out of range
    def test_bad_subscribe_args(self, server):
        addr = 'test@testme12.com.net'
        user_token = self.apiserver.get_user_token(addr)
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

        post('subscribe', expected_status=200, data=basic_args)

        for (arg, val) in tests:
            testargs = dict(basic_args)
            testargs[arg] = val
            print(f'trying to set {arg} to {val}: {testargs}')
            post('subscribe', expected_status=400, data=testargs)

    # Test one-click unsubscribe -- the link at the bottom of each
    # email which gives unsubscribe privileges but not full management
    # privileges
    def test_oneclick_unsubscribe(self):
        addr = 'testnumberthree@test.com'
        user_token = self.apiserver.get_user_token(addr)

        # first subscription
        sub1 = self.sub_args(user_token)
        sub1['lat'] = 23.45
        sub1['lon'] = -123.321
        resp1 = post('subscribe', data=sub1).json()
        assert resp1['email'] == addr
        assert len(resp1['subs']) == 1

        # second subscription
        sub2 = self.sub_args(user_token)
        sub2['lat'] = 11.11
        sub2['lon'] = 22.22
        resp2 = post('subscribe', data=sub2).json()
        assert resp2['email'] == addr
        assert len(resp2['subs']) == 2

        # make sure there are two subscriptons returned from get_config
        resp3 = get('get_config', params={'user_token': user_token}).json()
        assert len(resp3['subs']) == 2

        # unsubscribe from sub1 using the uuid-only API
        resp4 = post('oneclick_unsubscribe', data={
            'uuid': resp1['subs'][0]['uuid']
        }).json()
        # make sure no personal data is returned from this API
        assert resp4.pop('success') is True
        assert resp4.pop('message') == \
            f'{addr} will no longer get notifications for sondes near ({sub1["lat"]}, {sub1["lon"]}).'
        assert resp4 == {}

        # use the authorized-user management api to get the config;
        # make sure sub1 is gone and sub2 is still there
        resp5 = get('get_config', params={'user_token': user_token}).json()
        assert resp5['email'] == addr
        assert len(resp5['subs']) == 1
        assert resp5['subs'][0]['lat'] == sub2['lat']
        assert resp5['subs'][0]['lon'] == sub2['lon']

    # Make sure we keep two accounts straight
    def test_two_accounts(self, server):
        # user 1
        addr1 = 'testuser_1@test.com'
        user_token1 = self.apiserver.get_user_token(addr1)
        sub1 = self.sub_args(user_token1)
        sub1['max_distance_mi'] = 111
        post('subscribe', data=sub1).json()

        # user 2
        addr2 = 'testuser_2@test.com'
        user_token2 = self.apiserver.get_user_token(addr2)
        sub2 = self.sub_args(user_token2)
        sub2['max_distance_mi'] = 222
        post('subscribe', data=sub2).json()

        # verify user 1
        resp1 = get('get_config', params={'user_token': user_token1}).json()
        assert resp1['email'] == addr1
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 111

        # verify user 2
        resp1 = get('get_config', params={'user_token': user_token2}).json()
        assert resp1['email'] == addr2
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 222


class FakeSondehub:
    def __init__(self, filename):
        fn = os.path.join(os.path.dirname(__file__), 'data', filename + '.json.bz2')
        with bz2.open(fn) as ifh:
            self._data = json.load(ifh)

    def get_sonde_data(self, params):
        if 'serial' in params:
            serial = params['serial']
            return {
                serial: self._data[serial]
            }
        return self._data

@pytest.mark.usefixtures("mock_aws")
@pytest.mark.usefixtures("server")
class Test_EmailNotifier:
    def subscribe_seattle(self, distance):
        addr = f'test.{distance}@supertest.com'
        user_token = self.apiserver.get_user_token(addr)
        post('subscribe', data={
            'user_token': user_token,
            'lat': '47.6426',
            'lon': '-122.32271',
            'max_distance_mi': str(distance),
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        })
        return addr

    def test_sends_notification(self, tmp_path):
        # Subscribe twice: 100 mile max and 1 mile max. Only one email should be
        # generated because the sonde in this dataset is 66 miles away.
        addr_yes = self.subscribe_seattle(100)
        addr_no = self.subscribe_seattle(1)

        args = argparse.Namespace()
        args.really_send = True
        args.external_images_root = tmp_path
        notifier = send_sonde_email.EmailNotifier(args, FakeSondehub('sondes-V1854526-66-miles-from-seattle'))
        notifier.process_all()

        sent_emails = self.ses_backend.sent_messages
        assert len(sent_emails) == 1
        sent_email = sent_emails[0]
        assert addr_yes in sent_email.destinations
        assert addr_no not in sent_email.destinations
        email_obj = email.message_from_string(sent_email.raw_data)
        body = base64.b64decode(email_obj.get_payload()[0].get_payload()[0].get_payload()).decode('utf8')
        assert 'V1854526' in body
