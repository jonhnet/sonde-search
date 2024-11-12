#!/usr/bin/env python3

import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.cache import get_sonde_summaries_as_dataframe
pd.options.mode.copy_on_write = True

def get_near_pairs(df, i):
    landing = df.iloc[i]
    mates = df.iloc[i + 1:]
    mates['dist'] = np.sqrt((landing['lat'] - mates['lat'])**2 + (landing['lon'] - mates['lon'])**2)
    return mates.loc[mates['dist'] < 0.01]

def get_close_landings(lat_min, lat_max, lon_min, lon_max):
    all = get_sonde_summaries_as_dataframe()
    all = all[['serial', 'frame', 'datetime', 'lat', 'lon']]
    landings = all.loc[all.groupby('serial')['frame'].idxmax()]
    near = landings.loc[(landings.lat >= lat_min) & (landings.lat <= lat_max)]
    near = near.loc[(near.lon >= lon_min) & (near.lon < lon_max)]

    dfs = []
    
    for i in range(len(near)):
        nearpairs = get_near_pairs(near, i)
        if not nearpairs.empty:
            new_df = nearpairs[['serial', 'dist']]
            new_df.insert(0, 'a', near.iloc[i]['serial'])
            dfs.append(new_df)

    closest = pd.concat(dfs).sort_values('dist').reset_index(drop=True)
    closest = closest.rename({'serial': 'b'}, axis=1)
    print(closest.head(20))


if __name__ == "__main__":
    get_close_landings(37, 42, -114, -109)
