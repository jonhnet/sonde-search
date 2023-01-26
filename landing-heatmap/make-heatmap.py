#!/usr/bin/env python3

import pandas as pd
import folium
from folium.plugins import HeatMap

# Read summaries
df = pd.read_parquet('sonde-summaries-2022.parquet')

# Get landings only
df = df.loc[(df.vel_v < 0) & (df.alt < 10000)]

# Get west coast only
df = df.loc[(df.lat > 30) & (df.lat < 55)]
df = df.loc[(df.lon > -125) & (df.lon < -100)]

# Draw heatmap
fmap = folium.Map()
hm = HeatMap(df[['lat', 'lon']])
hm.add_to(fmap)
fmap.save("west-coast-sondes-2022.html")
