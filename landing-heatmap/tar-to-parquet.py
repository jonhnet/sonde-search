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

import io
import json
import os
import pandas as pd
import sys
import tarfile

def get_recs_from_tar(infilename):
    num_files = 0
    num_recs = 0

    with tarfile.open(infilename) as archive:
        for f in archive:
            if not f.isfile():
                continue
            num_files += 1

            try:
                j = json.load(archive.extractfile(f.name))
            except json.decoder.JSONDecodeError:
                print(f"error parsing json: {f}")
                continue

            for rec in j:
                num_recs += 1
                yield rec

            if num_files % 100 == 0:
                print(f"found {num_recs} records in {num_files} files ({f})")

def convert(infilename):
    df = pd.DataFrame(get_recs_from_tar(infilename))
    df.to_parquet(os.path.splitext(infilename)[0] + ".before.parquet")
    df = df.astype({
        'alt': float,
        'vel_v': float,
        'vel_h': float,
        'lat': float,
        'lon': float,
    })
    df.to_parquet(os.path.splitext(infilename)[0] + ".parquet")

if __name__ == "__main__":
    convert(sys.argv[1])
    
