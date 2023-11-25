#!/usr/bin/env python3

#
# This converts a tar file full of json files from sondehub's by-date archive in
# their S3 bucket into a Pandas dataframe and saves it as a Parquet file. This
# makes the files far easier to access: a year of data is about 200k json files
# and it takes tens of minutes to open and parse all of them. The parqet file,
# on the other hand, can be loaded in a couple of seconds.
#
# 1) aws s3 sync --no-sign-request s3://sondehub-history/date/2023 .
# 2) tar cvfz sondehub-2023.tgz .
# 3) ./tar-to-parquet.py sondehub-2023.tgz
#
# Perhaps it'd be simpler to just have this script walk the directory tree
# itself, but at the time I wrote it, I'd already tarred up the files and
# deleted the original.
#

import json
import os
import pandas as pd
import pytz
import sys
import tarfile
import time


def is_valid_record(recs, fname):
    if len(recs) % 3 != 0:
        print(f'tossing invalid file {fname} with {len(recs)} recs')
        return False

    frame_nums = [int(rec['frame']) for rec in recs]

    if not (frame_nums[0] <= frame_nums[1] <= frame_nums[2]):
        print(f'out of order frames in {fname}: {frame_nums}')
        return False

    for frame_num in frame_nums:
        if frame_num < 0 or frame_num > 4_000_000_000:
            print(f'invalid frame number {frame_num} in {fname}')
            return False

    try:
        for rec in recs:
            d = pd.to_datetime(rec['datetime'])
            if d.tzinfo is None:
                d = pytz.utc.localize(d)
            rec['datetime'] = d
    except Exception as e:
        print(f'invalid datetime {rec["datetime"]}: {e}: {fname}')
        return False

    for rec in recs:
        rec['archive_source'] = fname

    return True


def get_recs_from_tar(infilename):
    with tarfile.open(infilename) as archive:
        fnames = [f.name for f in archive if f.isfile()]

        num_files = 0
        num_recs = 0
        start_time = time.time()

        for fname in fnames:
            num_files += 1

            try:
                j = json.load(archive.extractfile(fname))
            except json.decoder.JSONDecodeError:
                print(f"error parsing json: {fname}")
                continue

            if not is_valid_record(j, fname):
                continue

            for rec in j:
                num_recs += 1
                yield rec

            if num_files % 100 == 0:
                dur = time.time() - start_time
                print(f"[{num_files}/{len(fnames)}] {num_recs} recs, {dur:.2f}s")
                start_time = time.time()


def convert(infilename):
    df = pd.DataFrame(get_recs_from_tar(infilename))
    df.to_pickle(os.path.splitext(infilename)[0] + ".before.pickle")
    df = df.astype({
        'alt': float,
        'vel_v': float,
        'vel_h': float,
        'lat': float,
        'lon': float,
        'temp': float,
        'humidity': float,
        'frame': int,
    })
    if 'frequency' in df:
        df['frequency'] = df['frequency'].astype(float)
    df['datetime'] = pd.to_datetime(df['datetime'])

    df.to_parquet(os.path.splitext(infilename)[0] + ".parquet")


if __name__ == "__main__":
    convert(sys.argv[1])
