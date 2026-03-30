#!/usr/bin/env python3

#
# This converts a tar file full of json files from sondehub's by-date archive in
# their S3 bucket into a Pandas dataframe and saves it as a Parquet file. This
# makes the files far easier to access: a year of data is about 200k json files
# and it takes tens of minutes to open and parse all of them. The parqet file,
# on the other hand, can be loaded in a couple of seconds.
#
# A) On an AWS host, so the transfer costs are lower
#   1) aws s3 sync --no-sign-request s3://sondehub-history/date/2023 .
#   2) tar cvfz sondehub-2023.tgz .
# B) On my home host, which has plenty of RAM
#   1) scp cambot:sondehub-2023.tgz .
#   2) ./tar-to-parquet.py sondehub-2023.tgz
#

import json
import os
import pandas as pd
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

    # Basic datetime sanity check — full parsing is done in bulk later,
    # which is ~100x faster than per-record pd.to_datetime() calls
    for rec in recs:
        dt = rec.get('datetime', '')
        if not isinstance(dt, str) or len(dt) < 10:
            print(f'invalid datetime {dt!r} in {fname}')
            return False

    for rec in recs:
        rec['archive_source'] = fname

    return True


def get_recs_from_tar(infilename):
    with tarfile.open(infilename) as archive:
        num_files = 0
        num_recs = 0
        start_time = time.time()

        for member in archive:
            if not member.isfile():
                continue

            num_files += 1

            try:
                j = json.load(archive.extractfile(member))
            except json.decoder.JSONDecodeError:
                print(f"error parsing json: {member.name}")
                continue

            if not is_valid_record(j, member.name):
                continue

            for rec in j:
                num_recs += 1
                yield rec

            if num_files % 10000 == 0:
                dur = time.time() - start_time
                print(f"[{num_files}] {num_recs} recs, {dur:.2f}s, "
                      f"{num_files/dur:.0f} files/sec")



NUMERIC_COLUMNS = [
    'alt', 'altErr', 'batt', 'burst_timer', 'crdErr', 'frame', 'freq',
    'frequency', 'fwver', 'heading', 'humidity', 'invalid_temp', 'lat',
    'launch_site_range_estimate', 'lon', 'mnfdate', 'pressure', 'rssi',
    'sats', 'snr', 'temp', 'tx_frequency', 'upload_time_delta',
    'uploader_alt', 'vel_h', 'vel_v',
]


def convert(infilename):
    df = pd.DataFrame(get_recs_from_tar(infilename))
    df.to_pickle(os.path.splitext(infilename)[0] + ".before.pickle")

    # Normalize column names
    if 'freq' in df.columns:
        if 'frequency' not in df.columns:
            df = df.rename(columns={'freq': 'frequency'})
        else:
            df['frequency'] = df['frequency'].fillna(df['freq'])
            df = df.drop(columns=['freq'])

    # Convert numeric columns, coercing bad values (empty strings, etc.) to NaN
    for col in NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df['datetime'] = pd.to_datetime(df['datetime'], format='ISO8601', utc=True)

    df.to_parquet(os.path.splitext(infilename)[0] + ".parquet")


if __name__ == "__main__":
    convert(sys.argv[1])
