#!/usr/bin/env python3

import pandas as pd
import sys
import datetime

def get_df(filename):
    data = open(filename).readlines()
    metadata = [line for line in data if line.startswith('#USM')]
    df = pd.DataFrame([line.split() for line in metadata])
    df = df.rename({
        1: 'year',
        2: 'month',
        3: 'day',
        4: 'nomhr',
        5: 'reltime',
        6: 'num_recs',
    }, axis=1)
    df = df.astype({
        'year': int,
        'month': int,
        'day': int,
        'nomhr': int,
        'reltime': int,
        'num_recs': int,
    })

    # filter out records that do not have a valid launch time
    df = df[df['reltime'] < 9999]

    # create a datetime object to represent the exact launch date and time.
    # nominal midnight launches are (i think) always launched the night before
    def get_launch_time(r):
        reltime = datetime.datetime(
            year=r['year'],
            month=r['month'],
            day=r['day'],
            hour=int(r['reltime']/100),
            minute=r['reltime']%100,
        )
        if r['nomhr'] == 0 and reltime.hour > 12:
            reltime -= datetime.timedelta(days=1)
        return pd.to_datetime(reltime)
    df['launch_dt'] = df.apply(get_launch_time, axis=1)

    df['nom_dt'] = df.apply(
        lambda r: pd.to_datetime(datetime.datetime(
            year=r['year'],
            month=r['month'],
            day=r['day'],
            hour=r['nomhr'],
        )), axis=1)

    return df


def main():
    in_filename = sys.argv[1]
    df = get_df(in_filename)
    df['year_month'] = df['launch_dt'].dt.to_period('M')
    df['nom_to_launch_minutes'] = df.apply(
        lambda r: (r['launch_dt'] - r['nom_dt']).total_seconds() / 60,
        axis=1)
    df = df[['year_month', 'nomhr', 'nom_to_launch_minutes']]
    groups = df.groupby(['year_month', 'nomhr'])
    launch_times = pd.concat([
        groups.min().rename({'nom_to_launch_minutes': 'launch_min'}, axis=1),
        groups.median().rename({'nom_to_launch_minutes': 'launch_median'}, axis=1),
        groups.max().rename({'nom_to_launch_minutes': 'launch_max'}, axis=1),
    ], axis=1)

    print(launch_times)

    # plot midnight launch times (mlt)
    mlt = launch_times.xs(0, level=1)
    ax = mlt.plot(figsize=(20, 10), grid=True)
    ax.figure.tight_layout()
    ax.figure.savefig(f"{in_filename}-launch-time-summary.png")

    # plot the last 24 months
    ax = mlt.tail(24).plot(figsize=(20, 10), grid=True)
    ax.figure.tight_layout()
    ax.figure.savefig(f"{in_filename}-launch-time-summary-recent.png")
    
main()
