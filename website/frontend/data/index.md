---
layout: page-fullwidth
title: "Sonde Raw Data"
footer: true
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

* [2021 Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2021.parquet)

* [2022 Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2022.parquet)

* [2023 Summaries](https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/sonde-summaries-2023.parquet)

## Example Usage

Python's popular data science library [Pandas](https://pandas.pydata.org/) is a
great way to explore the data. For example, to see how many launches there were
in 2022:

```
In [1]: import pandas as pd

In [2]: df = pd.read_parquet("sonde-summaries-2022.parquet")

In [3]: df['serial'].nunique()
Out[3]: 140629
```
The `datetime` column lets you see how many launches are in the dataset broken down by month:

```
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
Line 4 takes just one record per serial number - recall there are at least 3
(and possibly more) rows in the dataset per serial number giving the first,
highest and last data points for each flight fed to SondeHub.

Line 5 takes the year out of the `datetime` field, uses the Pandas
`value_counts()` function to count how many times each year appears, then sorts
the months numerically.

There are endless other ways Pandas can be used to analyze sonde data. For some
other examples, see my code on GitHub that [draws a landing
calendar](https://github.com/jonhnet/sonde-search/blob/main/analyzers/landings-by-season.py)
showing where sondes tend to land each month.
