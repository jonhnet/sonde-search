import pandas as pd
import os
import requests
import time
import bz2
import json
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../'))
from lib.map_utils import get_elevation


# Get sonde data from the same live API that the SondeHub web site uses
class SondeHubRetrieverBase:
    MAX_SONDEHUB_TRIES = 6

    def __init__(self):
        pass

    # These should be overridden in subclasses
    def make_telemetry_request(self, params):
        raise NotImplementedError

    def make_singlesonde_request(self, serial):
        raise NotImplementedError

    def cleanup_sonde_data(self, sondes):
        # Sometimes lat/lon comes as a string instead of float
        try:
            sondes = sondes.astype({
                'alt': float,
                'lat': float,
                'lon': float,
            })
            if 'vel_v' in sondes and 'vel_h' in sondes:
                sondes = sondes.astype({
                    'vel_v': float,
                    'vel_h': float,
                })
        except Exception as e:
            print(f'Error converting sondehub data to floats: {e}')
            print(sondes.columns)
            print(sondes.iloc[0])
            raise

        sondes['datetime'] = pd.to_datetime(sondes['datetime'])

        return sondes

    def get_telemetry_once(self, params):
        response, now = self.make_telemetry_request(params)

        def unpack_list():
            for serial, timeblocks in response.items():
                for timestamp, record in timeblocks.items():
                    yield record
        sondes = pd.DataFrame(unpack_list())
        return sondes, now

    def get_singlesonde_once(self, serial):
        response, now = self.make_singlesonde_request(serial)
        sonde = pd.DataFrame(response)
        return sonde, now

    def get_sonde_data(self, params):
        tries = 1
        while True:
            try:
                if 'serial' in params:
                    sondes, now = self.get_singlesonde_once(params['serial'])
                else:
                    sondes, now = self.get_telemetry_once(params)
            except Exception as e:
                if tries >= self.MAX_SONDEHUB_TRIES:
                    print(f"Couldn't get sondehub data, even after {self.MAX_SONDEHUB_TRIES} tries!")
                    raise e

                print(f"Failure {tries} retrieving data from Sondehub ({e}); retrying after a short sleep...")
                time.sleep((2**tries) * 2)
                tries += 1
                continue

            if not sondes.empty:
                sondes = self.cleanup_sonde_data(sondes)
            return sondes, now

# Subclass of SondeHubRetriever that gets real data from the live service on the
# Internet
class LiveSondeHub(SondeHubRetrieverBase):
    SONDEHUB_DATA_URL     = 'https://api.v2.sondehub.org/sondes/telemetry'
    SONDEHUB_ONESONDE_URL = 'https://api.v2.sondehub.org/sonde/'

    def __init__(self):
        super(LiveSondeHub, self).__init__()

    def make_telemetry_request(self, params):
        response = requests.get(self.SONDEHUB_DATA_URL, params=params)
        response.raise_for_status()
        return response.json(), pd.Timestamp.utcnow()

    def make_singlesonde_request(self, serial):
        response = requests.get(self.SONDEHUB_ONESONDE_URL + serial)
        response.raise_for_status()
        return response.json(), pd.Timestamp.utcnow()

    def get_elevation_data(self, lat, lon):
        return get_elevation(lat, lon)

class FakeSondeHub(SondeHubRetrieverBase):
    def __init__(self, filename):
        fn = os.path.join(os.path.dirname(__file__), '..', 'tests', 'data', filename + '.json.bz2')
        with bz2.open(fn) as ifh:
            self._data = json.load(ifh)

        # Convert the singlesonde format to the telemetry format, for consistency
        if 'singlesonde' in filename:
            serial = self._data[0]['serial']
            print(f'loading fake {serial}')
            self._data = {
                serial: {rec['datetime']: rec for rec in self._data}
            }

        self._time = None
        for serial, timeblocks in self._data.items():
            for timestamp, record in timeblocks.items():
                if 'datetime' in record:
                    ts = pd.to_datetime(record['datetime'])
                    if not self._time or ts > self._time:
                        self._time = ts
        print(f"{filename} fake time: {self._time}")

    def make_telemetry_request(self, params):
        assert 'serial' not in params
        return self._data, self._time

    def make_singlesonde_request(self, serial):
        records = self._data[serial].values()
        return records, self._time

    def get_elevation_data(self, lat, lon):
        return 100

def dynamodb_to_dataframe(operation, **query_args):
    df_list = []

    response = operation(**query_args)
    while True:
        df_list.append(pd.DataFrame(response['Items']))
        if 'LastEvaluatedKey' in response:
            query_args['ExclusiveStartKey'] = response['LastEvaluatedKey']
            response = operation(**query_args)
        else:
            if len(df_list) == 0:
                return pd.DataFrame()
            else:
                return pd.concat(df_list)
