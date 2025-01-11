#!/usr/bin/env python3

import folium
from folium.plugins import HeatMap
import branca.element
import sys
sys.path.insert(0, "..")
from data.cache import get_sonde_summaries_as_dataframe, years_covered

EXTRA_STYLE = branca.element.Element('''
<style>
  .leaflet-heatmap-layer {
     opacity: 0.7;
  }
</style>
''')

def draw_map(df, name, **kwargs):
    # Draw heatmap
    fmap = folium.Map(**kwargs)
    hm = HeatMap(df[['lat', 'lon']])
    hm.add_to(fmap)
    fmap.get_root().header.add_child(EXTRA_STYLE)
    fmap.save(name)


def main():
    # Read summaries
    df = get_sonde_summaries_as_dataframe()
    years = years_covered(df)
    range_string = f"{years[0]}-{years[-1]}"

    print(f"Plotting data for years {range_string}")

    # Get landings only
    df = df.loc[(df.vel_v < 0) & (df.alt < 10000)]
    draw_map(
        df,
        f"worldwide-sonde-landings-{range_string}.html",
        location=[20, 0],
        zoom_start=2,
        max_zoom=11,
    )

    # Get the US only
    ndf = df
    ndf = ndf.loc[(ndf.lat > 20) & (ndf.lat < 55)]
    ndf = ndf.loc[(ndf.lon > -125) & (ndf.lon < -66)]
    draw_map(
        ndf,
        f"us-sonde-landings-{range_string}.html",
        location=[40, -99],
        zoom_start=4,
        max_zoom=11,
    )

    # Get the west coast only
    ndf = df
    ndf = ndf.loc[(ndf.lat > 30) & (ndf.lat < 55)]
    ndf = ndf.loc[(ndf.lon > -125) & (ndf.lon < -100)]
    draw_map(
        ndf,
        f"west-coast-sonde-landings-{range_string}.html", location=[40, -120], zoom_start=4,)


if __name__ == "__main__":
    main()
