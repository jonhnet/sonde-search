from moto import mock_aws
from moto.core import DEFAULT_ACCOUNT_ID
from moto.ses import ses_backends
from moto.ses.models import RawMessage
from pathlib import Path
from typing import Dict
import argparse
import base64
import boto3
import cherrypy
import email
import email.header
import json
import os
import pytest
import re
import requests
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import v2, send_sonde_email, table_definitions, constants, util

@pytest.fixture
def sonde_mock_aws(request):
    _mock = mock_aws()
    _mock.start()

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

    _mock.stop()

# general strategy for doing unit tests with cherrypy cribbed from:
#   https://schneide.blog/2017/02/06/integration-tests-with-cherrypy-and-requests/
@pytest.fixture
def server(request, sonde_mock_aws):
    api = util.FakeSondeHub('V1854526-singlesonde')
    api.MAX_SONDEHUB_RETRIES = 1
    request.cls.apiserver = v2.mount_server_instance(api, dev_mode=True)
    request.cls.user_tokens = {}
    cherrypy.config.update({
        'request.throw_errors': True,
    })
    cherrypy.engine.start()
    cherrypy.engine.wait(cherrypy.engine.states.STARTED)
    yield
    cherrypy.engine.exit()
    cherrypy.engine.block()

def get(url_suffix, expected_status=200, params=None, cookies=None):
    url = f'http://127.0.0.1:8080/{url_suffix}'
    resp = requests.get(url, params=params, cookies=cookies)
    assert resp.status_code == expected_status, f"Got error: {resp.text}"
    return resp

def post(url_suffix, expected_status=200, data=None, cookies=None):
    url = f'http://127.0.0.1:8080/{url_suffix}'
    resp = requests.post(url, data=data, cookies=cookies)
    assert resp.status_code == expected_status, f"Got error: {resp.text}"
    return resp

@pytest.mark.usefixtures("server")
class Test_v2:
    ses_backend: ses_backends
    apiserver: v2.SondesearchAPI

    def sub_args(self, user_token):
        return {
            'data': {
                'lat': '77.123456789',
                'lon': '0.1',
                'max_distance_mi': '300',
                'units': 'imperial',
                'tzname': 'America/Los_Angeles',
            },
            'cookies': {
                'notifier_user_token_v2': user_token,
            },
        }

    def test_hello(self):
        resp = get('hello')
        assert 'hello from the v2 sondesearch api' in resp.text

    # Ensure that for a new user, the email address returned for the
    # token corresponds to the email address we generated the token
    # for. The response shouldn't have anything else in it.
    def test_get_config_newuser(self):
        addr = 'test@foo.bar'
        user_token = self.apiserver.get_user_token_from_email(addr)
        resp = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert resp.pop('email') == addr
        assert resp.pop('prefs') == {}
        assert resp.pop('subs') == []
        assert resp == {}

        # Also test to ensure we get an empty notification history
        history = get('get_notification_history', cookies={
            'notifier_user_token_v2': user_token,
        }).json()
        assert history == []

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
        user_token = self.apiserver.get_user_token_from_email(addr)
        assert mo.group(1) == user_token

    # Test subscribing, then unsubscribing, as if we're using the
    # management portal
    def test_subscribe_unsubscribe(self):
        addr = 'test@testme2.net'
        user_token = self.apiserver.get_user_token_from_email(addr)
        sub_args = self.sub_args(user_token)
        resp = post('subscribe', **sub_args).json()
        assert resp['email'] == addr
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]
        test_sub = sub_args['data']
        assert sub['lat'] == float(test_sub['lat'])
        assert sub['lon'] == float(test_sub['lon'])
        assert sub['max_distance_mi'] == float(test_sub['max_distance_mi'])
        assert resp['prefs']['units'] == test_sub['units']
        assert resp['prefs']['tzname'] == test_sub['tzname']

        # Get config and ensure we get the same config block back again
        resp2 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert resp == resp2

        # Ensure we get an empty notification history
        history = get('get_notification_history', cookies={
            'notifier_user_token_v2': user_token,
        }).json()
        assert history == []

        # Unsubscribe
        resp3 = post('managed_unsubscribe', data={
            'uuid': sub['uuid'],
        }, cookies={
            'notifier_user_token_v2': user_token,
        }).json()

        assert len(resp3['subs']) == 0
        assert resp3['email'] == addr

        # Get config again, ensure it's the same as the unsubscribe response
        resp4 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert resp3 == resp4

    def test_unsubscribe_without_cookies(self, server):
        addr = 'test@testme2.net'
        user_token = self.apiserver.get_user_token_from_email(addr)
        sub_args = self.sub_args(user_token)
        resp = post('subscribe', **sub_args).json()
        assert resp['email'] == addr
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]

        # Try to unsubscribe without a cookie, ensure we get a nerror
        post('managed_unsubscribe', expected_status=400, data={
            'uuid': sub['uuid'],
        })

        # Make sure the subscription is still there
        resp3 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert len(resp3['subs']) == 1

        # Unsubscribe with wrong cookie
        post('managed_unsubscribe', expected_status=500, data={
            'uuid': sub['uuid'],
        }, cookies={
            'notifier_user_token_v2': 'foo'
        })
        resp4 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert len(resp4['subs']) == 1

        # Unsubscribe with right cookie
        post('managed_unsubscribe', expected_status=200, data={
            'uuid': sub['uuid'],
        }, cookies={
            'notifier_user_token_v2': user_token,
        })
        resp5 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert len(resp5['subs']) == 0

    def test_edit_subscription(self, server):
        addr = 'test@testme2.net'
        user_token = self.apiserver.get_user_token_from_email(addr)
        sub_args = self.sub_args(user_token)
        resp = post('subscribe', **sub_args).json()

        # Ensure the initial subscription is correct
        assert resp['email'] == addr
        assert len(resp['subs']) == 1
        sub = resp['subs'][0]
        test_sub = sub_args['data']
        assert sub['lat'] == float(test_sub['lat'])
        assert sub['lon'] == float(test_sub['lon'])
        assert sub['max_distance_mi'] == float(test_sub['max_distance_mi'])
        assert resp['prefs']['units'] == test_sub['units']
        assert resp['prefs']['tzname'] == test_sub['tzname']

        # Change the max distance and edit the subscription
        sub_args['data']['max_distance_mi'] = '150'
        sub_args['data']['replace_uuid'] = sub['uuid']
        resp2 = post('subscribe', **sub_args).json()

        # Ensure the subscription has been edited
        assert resp2['email'] == addr
        assert len(resp2['subs']) == 1
        sub2 = resp2['subs'][0]
        test_sub = sub_args['data']
        assert sub2['lat'] == float(test_sub['lat'])
        assert sub2['lon'] == float(test_sub['lon'])
        assert sub2['max_distance_mi'] == float(test_sub['max_distance_mi'])
        assert resp2['prefs']['units'] == test_sub['units']
        assert resp2['prefs']['tzname'] == test_sub['tzname']

    # Test making a subscription, then losing your credentials and
    # asking for another auth link to be emailed. Your subscription
    # state should be retained.
    def test_lost_credentials(self, server):
        addr = 'lost-credentials@test.net'
        user_token = self.apiserver.get_user_token_from_email(addr)
        resp = post('subscribe', **self.sub_args(user_token)).json()
        assert resp['email'] == addr
        assert len(resp['subs']) == 1

        # ask for new credentials and make sure the sub is still there. We ask
        # for uppercase email address to test the case-insensitivity of email
        # lookup
        user_token2 = self.apiserver.get_user_token_from_email(addr.upper())

        resp2 = get('get_config', cookies={'notifier_user_token_v2': user_token2}).json()
        assert resp == resp2

    def test_multiple_subscriptions(self, server):
        addr = 'test@testme'
        user_token = self.apiserver.get_user_token_from_email(addr)
        templ = self.sub_args(user_token)
        templ['data']['lat'] = '1'
        templ['data']['lon'] = '1'
        resp = post('subscribe', **templ).json()
        assert len(resp['subs']) == 1

        templ['data']['lat'] = '2'
        templ['data']['lon'] = '2'
        resp = post('subscribe', **templ).json()
        assert len(resp['subs']) == 2

        templ['data']['lat'] = '3'
        templ['data']['lon'] = '3'
        resp = post('subscribe', **templ).json()
        assert len(resp['subs']) == 3

        # unsub from 1 and 3
        for sub in resp['subs']:
            if sub['lat'] != 2:
                post('managed_unsubscribe', data={
                    'uuid': sub['uuid'],
                }, cookies={
                    'notifier_user_token_v2': user_token,
                })

        # make sure 2 remains
        resp = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert len(resp['subs']) == 1
        assert resp['subs'][0]['lat'] == 2
        assert resp['subs'][0]['lon'] == 2

    # Test subscribing with a missing argument
    def test_missing_subscribe(self, server):
        addr = 'test@testme'
        user_token = self.apiserver.get_user_token_from_email(addr)
        basic_args = self.sub_args(user_token)

        # make sure the basic args work
        post('subscribe', expected_status=200, **basic_args)

        for arg in basic_args['data']:
            testargs = {
                'data': dict(basic_args['data']),
                'cookies': basic_args['cookies'],
            }
            testargs['data'].pop(arg)
            resp = post('subscribe', expected_status=400, **testargs)
            assert f'missing argument: {arg}' in resp.text

    # Test subscribing with various arguments out of range
    def test_bad_subscribe_args(self, server):
        addr = 'test@testme12.com.net'
        user_token = self.apiserver.get_user_token_from_email(addr)
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

        post('subscribe', expected_status=200, **basic_args)

        for (arg, val) in tests:
            testargs = {
                'data': dict(basic_args['data']),
                'cookies': basic_args['cookies'],
            }
            testargs['data'][arg] = val
            print(f'trying to set {arg} to {val}: {testargs}')
            post('subscribe', expected_status=400, data=testargs)

    # Test one-click unsubscribe -- the link at the bottom of each
    # email which gives unsubscribe privileges but not full management
    # privileges
    def test_oneclick_unsubscribe(self):
        addr = 'testnumberthree@test.com'
        user_token = self.apiserver.get_user_token_from_email(addr)

        # first subscription
        sub1 = self.sub_args(user_token)
        sub1['data']['lat'] = 23.45
        sub1['data']['lon'] = -123.321
        resp1 = post('subscribe', **sub1).json()
        assert resp1['email'] == addr
        assert len(resp1['subs']) == 1

        # second subscription
        sub2 = self.sub_args(user_token)
        sub2['data']['lat'] = 11.11
        sub2['data']['lon'] = 22.22
        resp2 = post('subscribe', **sub2).json()
        assert resp2['email'] == addr
        assert len(resp2['subs']) == 2

        # make sure there are two subscriptons returned from get_config
        resp3 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert len(resp3['subs']) == 2

        # unsubscribe from sub1 using the uuid-only API
        resp4 = post('oneclick_unsubscribe', data={
            'uuid': resp1['subs'][0]['uuid']
        }).json()
        # make sure no personal data is returned from this API
        assert resp4.pop('success') is True
        assert resp4.pop('cancelled_sub_lat') == sub1['data']['lat']
        assert resp4.pop('cancelled_sub_lon') == sub1['data']['lon']
        assert resp4 == {}

        # use the authorized-user management api to get the config;
        # make sure sub1 is gone and sub2 is still there
        resp5 = get('get_config', cookies={'notifier_user_token_v2': user_token}).json()
        assert resp5['email'] == addr
        assert len(resp5['subs']) == 1
        assert resp5['subs'][0]['lat'] == sub2['data']['lat']
        assert resp5['subs'][0]['lon'] == sub2['data']['lon']

    # Make sure we keep two accounts straight
    def test_two_accounts(self, server):
        # user 1
        addr1 = 'testuser_1@test.com'
        user_token1 = self.apiserver.get_user_token_from_email(addr1)
        sub1 = self.sub_args(user_token1)
        sub1['data']['max_distance_mi'] = 111
        post('subscribe', **sub1).json()

        # user 2
        addr2 = 'testuser_2@test.com'
        user_token2 = self.apiserver.get_user_token_from_email(addr2)
        sub2 = self.sub_args(user_token2)
        sub2['data']['max_distance_mi'] = 222
        post('subscribe', **sub2).json()

        # verify user 1
        resp1 = get('get_config', cookies={'notifier_user_token_v2': user_token1}).json()
        assert resp1['email'] == addr1
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 111

        # verify user 2
        resp1 = get('get_config', cookies={'notifier_user_token_v2': user_token2}).json()
        assert resp1['email'] == addr2
        assert len(resp1['subs']) == 1
        assert resp1['subs'][0]['max_distance_mi'] == 222

    def test_kml_conversion(self, server):
        resp = get('get_sonde_kml', params={'serial': 'V1854526'})

        import xml.etree.ElementTree as ET
        tree = ET.fromstring(resp.text)

        assert tree.tag.endswith('}kml')


@pytest.mark.usefixtures("sonde_mock_aws")
@pytest.mark.usefixtures("server")
class Test_EmailNotifier:
    apiserver: v2.SondesearchAPI
    ses_backend: ses_backends
    user_tokens: Dict[str, str]

    def get_body(self, sent_email: RawMessage) -> str:
        email_obj = email.message_from_string(sent_email.raw_data)
        body = base64.b64decode(email_obj.get_payload()[0].get_payload()[0].get_payload()).decode('utf8')
        return body

    def get_subject(self, sent_email: RawMessage) -> str:
        email_obj = email.message_from_string(sent_email.raw_data)
        subj_enc, encoding = email.header.decode_header(email_obj['Subject'])[0]
        return subj_enc.decode(encoding)

    def is_ground_reception(self, sent_email: RawMessage):
        body_gr = 'Ground Reception' in self.get_body(sent_email)
        subj_gr = self.get_subject(sent_email).startswith('GROUND RECEPTION')

        assert body_gr == subj_gr
        return body_gr

    def subscribe(self, distance, lat=47.6426, lon=-122.32271):
        addr = f'test.{distance}@supertest.com'
        user_token = self.apiserver.get_user_token_from_email(addr)
        self.user_tokens[addr] = user_token
        post('subscribe', data={
            'lat': str(lat),
            'lon': str(lon),
            'max_distance_mi': str(distance),
            'units': 'imperial',
            'tzname': 'America/Los_Angeles',
        }, cookies={
            'notifier_user_token_v2': user_token,
        })
        return addr

    def run_notifier(self, tmp_path, filename):
        args = argparse.Namespace()
        args.really_send = True
        args.external_images_root = tmp_path
        args.live_test = False
        sh = util.FakeSondeHub(filename)
        sh.MAX_SONDEHUB_RETRIES = 1
        notifier = send_sonde_email.EmailNotifier(args, sh)
        notifier.process_all_subs()

        return self.ses_backend.sent_messages

    def test_sends_notification(self, tmp_path: Path):
        # Subscribe twice: 100 mile max and 1 mile max. Only one email should be
        # generated because the sonde in this dataset is 66 miles away.
        addr_yes = self.subscribe(distance=100)
        addr_no = self.subscribe(distance=1)

        sent_emails = self.run_notifier(tmp_path, 'sondes-V1854526-66-miles-from-seattle')
        # Run again and ensure there are no duplicate notifications
        sent_emails = self.run_notifier(tmp_path, 'sondes-V1854526-66-miles-from-seattle')
        assert len(sent_emails) == 1
        sent_email = sent_emails[0]
        assert addr_yes in sent_email.destinations
        assert addr_no not in sent_email.destinations
        body = self.get_body(sent_email)
        assert 'V1854526' in body
        assert not self.is_ground_reception(sent_email)

    # Ensure we send more than one notification if there's more than one sonde
    # in range. In this particular test input we have the following sondes
    # within 300 miles of the Seattle test location:
    #
    # sonde V1854526, range 65.6, landed at 2023-12-08 13:00:13+00:00
    # sonde V1050122, range 235.8, landed at 2023-12-08 12:58:18+00:00
    # sonde V3621107, range 250.1, landed at 2023-12-08 13:17:23+00:00
    # sonde 23040510, range 252.8, landed at 2023-12-08 13:40:15+00:00
    def test_multi_notifications(self, tmp_path: Path):
        addr = self.subscribe(distance=240)
        sent_emails = self.run_notifier(tmp_path, 'sondes-V1854526-66-miles-from-seattle')
        assert len(sent_emails) == 2
        EXPECTED_SONDES = ['V1854526', 'V1050122']
        for i, serial in enumerate(EXPECTED_SONDES):
            sent_email = sent_emails[i]
            assert addr in sent_email.destinations
            body = self.get_body(sent_email)
            assert serial in body
            assert not self.is_ground_reception(sent_email)

        # Also test to ensure we get notification history
        history = post('get_notification_history', cookies={
            'notifier_user_token_v2': self.user_tokens[addr],
        }).json()
        print(json.dumps(history, indent=2))
        assert len(history) == len(EXPECTED_SONDES)
        history_serials = [rec['serial'] for rec in history]
        assert sorted(history_serials) == sorted(EXPECTED_SONDES)

    # No notification should be sent if the sonde is still in the air
    def test_no_email_for_airborne(self, tmp_path: Path):
        self.subscribe(distance=40, lat=50, lon=8)
        sent_emails = self.run_notifier(tmp_path, 'sondes-V1854526-66-miles-from-seattle')
        assert len(sent_emails) == 0

    # Test to ensure we gracefully handle receivers that have no lat/lon info
    def test_nolatlon_receiver(self, tmp_path: Path):
        addr = self.subscribe(distance=100)
        sent_emails = self.run_notifier(tmp_path, 'no-latlon-receiver-seattle')
        assert len(sent_emails) == 1
        sent_email = sent_emails[0]
        assert addr in sent_email.destinations
        body = self.get_body(sent_email)
        assert 'V1854451' in body

    def test_ground_reception(self, tmp_path: Path):
        addr = self.subscribe(distance=100, lat=41, lon=-112)
        sent_emails = self.run_notifier(tmp_path, 'ground-reception/ground-reception-23037859')
        assert len(sent_emails) == 1
        sent_email = sent_emails[0]
        assert addr in sent_email.destinations
        body = self.get_body(sent_email)
        assert '23037859' in body
        assert self.is_ground_reception(sent_email)
