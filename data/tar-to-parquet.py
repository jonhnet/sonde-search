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
from collections import Counter
from datetime import timedelta


NUMERIC_COLUMNS = [
    'alt', 'altErr', 'batt', 'burst_timer', 'crdErr', 'frame', 'freq',
    'frequency', 'fwver', 'heading', 'humidity', 'invalid_temp', 'lat',
    'launch_site_range_estimate', 'lon', 'mnfdate', 'pressure', 'rssi',
    'sats', 'snr', 'temp', 'tx_frequency', 'upload_time_delta',
    'uploader_alt', 'vel_h', 'vel_v',
]


class TarToParquetConverter:
    def __init__(self, infilename):
        self.infilename = infilename
        self.num_files = 0
        self.num_recs = 0
        self.drop_reasons = Counter()

    def _drop(self, reason):
        self.drop_reasons[reason] += 1
        return False

    def _is_valid_record(self, recs, fname):
        if len(recs) % 3 != 0:
            return self._drop('invalid record count (not multiple of 3)')

        try:
            frame_nums = [int(rec['frame']) for rec in recs]
        except (ValueError, KeyError):
            return self._drop('missing or non-numeric frame')

        for frame_num in frame_nums:
            if frame_num < 0 or frame_num > 4_000_000_000:
                return self._drop('frame number out of range')

        # Basic datetime sanity check — full parsing is done in bulk later,
        # which is ~100x faster than per-record pd.to_datetime() calls
        for rec in recs:
            dt = rec.get('datetime', '')
            if not isinstance(dt, str) or len(dt) < 10:
                return self._drop('invalid datetime')

        for rec in recs:
            rec['archive_source'] = fname

        return True

    def _get_recs_from_tar(self):
        start_time = time.time()

        with tarfile.open(self.infilename) as archive:
            for member in archive:
                if not member.isfile():
                    continue

                self.num_files += 1

                try:
                    j = json.load(archive.extractfile(member))
                except json.decoder.JSONDecodeError:
                    self._drop('JSON parse error')
                    continue

                if not self._is_valid_record(j, member.name):
                    continue

                for rec in j:
                    self.num_recs += 1
                    yield rec

                if self.num_files % 10000 == 0:
                    dur = time.time() - start_time
                    print(f"{self.num_files:>7,} files  "
                          f"{self.num_recs:>7,} records  "
                          f"{dur:>5.1f}s  "
                          f"{self.num_files / dur:>7,.0f} files/sec")

    def convert(self):
        print(f"Converting {self.infilename}")
        start_time = time.time()
        df = pd.DataFrame(self._get_recs_from_tar())
        extract_dur = time.time() - start_time

        basename = os.path.splitext(self.infilename)[0]

        # Normalize column names
        if 'freq' in df.columns:
            if 'frequency' not in df.columns:
                df = df.rename(columns={'freq': 'frequency'})
            else:
                df['frequency'] = df['frequency'].fillna(df['freq'])
                df = df.drop(columns=['freq'])

        # Convert numeric columns, coercing bad values (empty strings, etc.)
        # to NaN
        for col in NUMERIC_COLUMNS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df['datetime'] = pd.to_datetime(
            df['datetime'], format='ISO8601', utc=True, errors='coerce'
        )
        num_bad_dt = df['datetime'].isna().sum()
        if num_bad_dt > 0:
            df = df.dropna(subset=['datetime'])
            self.drop_reasons['unparseable datetime'] = int(num_bad_dt)

        # Drop sonde-reuse records: files where the time span between
        # records exceeds 24 hours indicate a sonde heard again days/months
        # later, making the landing position invalid.
        grouped = df.groupby('archive_source')['datetime']
        span = grouped.transform('max') - grouped.transform('min')
        reuse_mask = span > timedelta(hours=24)
        num_reuse = reuse_mask.sum()
        if num_reuse > 0:
            df = df[~reuse_mask]
            self.drop_reasons['time span > 24h (likely sonde reuse)'] = num_reuse

        df.to_parquet(basename + ".parquet")
        total_dur = time.time() - start_time

        # Print summary
        total_dropped = sum(self.drop_reasons.values())
        print(f"\nProcessed {self.num_files:,} files -> "
              f"{self.num_recs:,} records in {total_dur:.1f}s "
              f"({self.num_files / extract_dur:.0f} files/sec)")
        if total_dropped:
            print(f"Dropped {total_dropped:,} files:")
            for reason, count in self.drop_reasons.most_common():
                print(f"  {count:>6,}  {reason}")
        print(f"Output: {basename}.parquet")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <input.tgz> [input2.tgz ...]",
              file=sys.stderr)
        sys.exit(1)

    for infilename in sys.argv[1:]:
        TarToParquetConverter(infilename).convert()


if __name__ == "__main__":
    main()
