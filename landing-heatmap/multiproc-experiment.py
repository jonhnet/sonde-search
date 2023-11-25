#!/usr/bin/env python3

#
#
# NOTE - DO NOT USE
#
# This was an attempt at parallelizing tar-to-parquet for better perf.
# Code here is left in a half-completed state because benchmarking showed
# unimpressive speedups.
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

import tempfile
import uuid
import orjson as json
import os
import pandas as pd
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor


class Worker:
    def __init__(self, infilename, outdir):
        self.archive = tarfile.open(infilename)
        self.outdir = outdir

    def _is_valid_record(self, j):
        return True

    def _convert_one_file(self, fname):
        try:
            j = json.loads(self.archive.extractfile(fname).read())
        except json.JSONDecodeError:
            return {}

        if self._is_valid_record(j):
            return j
        else:
            return {}

    def _convert_multiple_files_to_records(self, fnames):
        for fname in fnames:
            for rec in self._convert_one_file(fname):
                yield rec

    def convert_multiple_to_df(self, fnames):
        start = time.time()
        df = pd.DataFrame(self._convert_multiple_files_to_records(fnames))

        df = df.astype({
            'alt': float,
            'vel_v': float,
            'vel_h': float,
            'lat': float,
            'lon': float,
#            'temp': float,
#            'frame': int,
        })

        dur = time.time() - start
        print(f"converted {len(fnames)} in {dur:.1f}sec starting from {fnames[0]}")

        outfile = os.path.join(self.outdir, uuid.uuid4().hex)
        #df.to_parquet(outfile + ".parquet")
        return outfile

worker = None

def make_worker(infilename, outdir):
    global worker
    worker = Worker(infilename, outdir)

def convert_multiple_to_df(fnames):
    global worker
    return worker.convert_multiple_to_df(fnames)

def convert(infilename):
    num_files = 0
    num_recs = 0

    with tarfile.open(infilename) as archive:
        fnames = []
        for f in archive:
            if not f.isfile():
                continue
            fnames.append(f.name)

        print(f"Trying to convert {len(fnames)} files")

        # Divide into chunks. The executors map function takes a "chunksize"
        # argument, but this still ends up pickling and unpickling each file's
        # json individually, which is low performance because they're so
        # small. Instead we want to pass a large chunk of files to the worker
        # and have each worker do the work of turning the records into a
        # dataframe in parallel.
        CHUNKSIZE = 1000
        chunks = [fnames[i:i+CHUNKSIZE] for i in range(0, len(fnames), CHUNKSIZE)]

        with tempfile.TemporaryDirectory() as tmpdir:
            with ProcessPoolExecutor(initializer=make_worker, initargs=(infilename,tmpdir), max_workers=1) as executor:
                fs = executor.map(convert_multiple_to_df, chunks)

if __name__ == "__main__":
    fn = sys.argv[1]
    convert(fn)
#    df = pd.DataFrame(convert(fn))
#    df.to_parquet(os.path.splitext(fn)[0] + ".parquet")
#        df.to_parquet(os.path.splitext(fn)[0] + ".parquet")
