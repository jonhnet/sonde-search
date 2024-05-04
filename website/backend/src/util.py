import pandas as pd
import os
import requests
import time
import bz2
import json

# Get sonde data from the same live API that the SondeHub web site uses
class SondeHubRetrieverBase:
    MAX_SONDEHUB_RETRIES = 6

    def __init__(self):
        pass

    # This should be overridden in subclasses
    def make_sonde_data_request(self, params):
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

    def get_sonde_data_once(self, params):
        try:
            response, now = self.make_sonde_data_request(params)
        except Exception as e:
            print(f'Error getting data from sondehub: {e}')
            return None, None

        def unpack_list():
            for sonde, timeblock in response.items():
                for _, record in timeblock.items():
                    yield record
        sondes = pd.DataFrame(unpack_list())
        return sondes, now

    def get_sonde_data(self, params):
        retries = 0
        while True:
            if retries > self.MAX_SONDEHUB_RETRIES:
                raise Exception(f"Couldn't get sondehub data, even after {self.MAX_SONDEHUB_RETRIES} retries")
            if retries > 0:
                print("Sondehub data failure; retrying after a short sleep...")
                time.sleep((2**retries) * 4)
            retries += 1
            sondes, now = self.get_sonde_data_once(params)
            if sondes is not None and len(sondes) == 0:
                print('Sondehub returned empty dataframe -- trying again')
                continue

            return self.cleanup_sonde_data(sondes), now

# Subclass of SondeHubRetriever that gets real data from the live service on the
# Internet
class LiveSondeHub(SondeHubRetrieverBase):
    SONDEHUB_DATA_URL = 'https://api.v2.sondehub.org/sondes/telemetry'

    def __init__(self):
        super(LiveSondeHub, self).__init__()

    def make_sonde_data_request(self, params):
        response = requests.get(self.SONDEHUB_DATA_URL, params=params)
        response.raise_for_status()
        return response.json(), pd.Timestamp.utcnow()

    def get_elevation_data(self, lat, lon):
        resp = requests.get('https://epqs.nationalmap.gov/v1/json', params={
            'x': lon,
            'y': lat,
            'units': 'Meters',
            'wkid': '4326',
            'includeDate': 'True',
        })
        resp.raise_for_status()
        return resp.json()

class FakeSondeHub(SondeHubRetrieverBase):
    def __init__(self, filename):
        fn = os.path.join(os.path.dirname(__file__), '..', 'tests', 'data', filename + '.json.bz2')
        with bz2.open(fn) as ifh:
            self._data = json.load(ifh)
        self._time = None
        for sondeid, receptions in self._data.items():
            for timestamp, datablock in receptions.items():
                if 'datetime' in datablock:
                    ts = pd.to_datetime(datablock['datetime'])
                    if not self._time or ts > self._time:
                        self._time = ts
        print(f"{filename} fake time: {self._time}")

    def make_sonde_data_request(self, params):
        if 'serial' in params:
            serial = params['serial']
            rv = {
                serial: self._data[serial]
            }
        else:
            rv = self._data

        return rv, self._time

    def get_elevation_data(self, lat, lon):
        return {'value': 100}

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
