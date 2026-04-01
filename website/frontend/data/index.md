---
layout: page-fullwidth
title: "Sonde Raw Data"
footer: true
comments: true
---

The historical maps on this site, such as the [heatmaps](/heatmaps) and
[calendars](/calendars) are all based on SondeHub data. SondeHub has graciously
[made their data public](https://github.com/projecthorus/sondehub-analysis).
However, it's not in a very convenient format: an enormous directory of hundreds
of thousands of individual JSON files. There's one file for every sonde ever
reported to SondeHub. Each file contains three records: the first, highest and
last data points reported to SondeHub for that sonde. It takes many hours to
download and parse them all.

I've downloaded the data, done some data conversion and cleaning to remove
apparently invalid flights, and reuploaded it in the
[Parquet](https://towardsdatascience.com/demystifying-the-parquet-file-format-13adb0206705)
format. Parquet is a far more efficient format, taking only seconds to download
and parse. It is supported by a wide variety of languages and analysis
frameworks.

## Data

I've broken the summary data into files per year for easier downloading:

* [2021
  Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2021.parquet) [43MB]

* [2022
  Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2022.parquet) [61MB]

* [2023
  Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2023.parquet) [71MB]

* [2024
  Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2024.parquet) [75MB]

* [2025
  Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2025.parquet) [78MB]

## Example Usage

Python's popular data science library [Pandas](https://pandas.pydata.org/) is a
great way to explore the data. For example, to see how many unique sondes were
reported in 2022:

```python
In [1]: import pandas as pd

In [2]: df = pd.read_parquet("sonde-summaries-2022.parquet")

In [3]: df['serial'].nunique()
Out[3]: 140629
```

Each sonde has 3 rows in the dataset: the first, highest, and last data points
reported to SondeHub. The `datetime` column lets you see how many launches there
were broken down by month:

```python
In [4]: launches = df.groupby('serial').first()

In [5]: launches['datetime'].dt.month.value_counts().sort_index()
Out[5]:
datetime
1     10423
2     10550
3     11812
4     10997
5     11658
6     11410
7     11718
8     12479
9     12514
10    12379
11    12561
12    12128
Name: count, dtype: int64
```

## Python Library (optional)

The parquet files above can be used directly with any language or tool that
supports parquet. But if you'd like some convenience, the [sonde-search
repo](https://github.com/jonhnet/sonde-search) includes a small Python
library that automatically downloads, caches, and concatenates all available
years of data for you.

### Loading the data

```python
from data.cache import get_sonde_summaries_as_dataframe

# Load all years, all columns
df = get_sonde_summaries_as_dataframe()
```

The parquet files contain over 50 columns, but most analyses only need a few.
Pass a `columns` parameter to load only what you need --- this is much faster
and uses far less memory:

```python
# Load only the columns needed for landing analysis
df = get_sonde_summaries_as_dataframe(
    columns=['serial', 'frame', 'lat', 'lon', 'alt', 'datetime']
)
```

### Filtering to real flights

The raw data includes ground-based transmitters, bench tests, and other
non-flights. The `filter_real_flights` function keeps only sondes that reached
at least 5,000m altitude and have started descending:

```python
from lib.data_utils import filter_real_flights, get_landing_rows

df = get_sonde_summaries_as_dataframe(
    columns=['serial', 'frame', 'lat', 'lon', 'alt', 'datetime']
)

# Remove ground tests and non-flights
df = filter_real_flights(df)
```

### Getting landing positions

Each sonde has multiple rows. To get just the landing position (the last
telemetry point received), use `get_landing_rows`:

```python
# One row per sonde: the last point received
landings = get_landing_rows(df)
```

### Putting it all together

Here's a complete example that finds all sondes that landed within 50km
of a given location:

```python
from geographiclib.geodesic import Geodesic
from data.cache import get_sonde_summaries_as_dataframe
from lib.data_utils import filter_real_flights, get_landing_rows

df = get_sonde_summaries_as_dataframe(
    columns=['serial', 'frame', 'lat', 'lon', 'alt', 'datetime']
)
df = filter_real_flights(df)
landings = get_landing_rows(df)

# Find landings within 50km of Seattle (47.6, -122.3)
home_lat, home_lon = 47.6, -122.3
landings['dist_km'] = landings.apply(
    lambda r: Geodesic.WGS84.Inverse(home_lat, home_lon, r['lat'], r['lon'])['s12'] / 1000,
    axis=1,
)
nearby = landings[landings['dist_km'] < 50].sort_values('dist_km')
print(f"{len(nearby)} sondes landed within 50km")
print(nearby[['serial', 'datetime', 'lat', 'lon', 'dist_km']].head(10))
```

For more examples, see the
[analyzers](https://github.com/jonhnet/sonde-search/tree/main/analyzers)
directory on GitHub, which includes code for generating [landing
calendars](https://github.com/jonhnet/sonde-search/blob/main/analyzers/landings-by-month.py)
and
[heatmaps](https://github.com/jonhnet/sonde-search/blob/main/analyzers/landings-heatmap.py).
