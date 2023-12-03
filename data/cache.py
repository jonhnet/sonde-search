#!/usr/bin/env python3

#
# library for retrieving data from the S3 bucket and parsing it
#

import os
import pandas as pd
import subprocess
import tempfile

YEARS_AVAILABLE = (2021, 2022, 2023)
BASE_URL = "https://sondesearch.lectrobox.com/vault/sonde-summaries/parquet/"
FILENAME_TEMPLATE = "sonde-summaries-{year}.parquet"


def get_sonde_summaries_as_dataframe():
    dirname = os.path.join(tempfile.gettempdir(), "sonde_summaries")
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    dfs = []
    for year in YEARS_AVAILABLE:
        filename = FILENAME_TEMPLATE.format(year=year)
        url = f'{BASE_URL}{filename}'

        # download the file into the temp directory (cache); if it's already
        # there, wget will not re-download it
        subprocess.check_call([
            "wget", "-nv", "-N", "--no-if-modified-since",
            url,
            "-P", dirname,
        ])

        # load and parse
        dfs.append(pd.read_parquet(os.path.join(dirname, filename)))

    return pd.concat(dfs)


if __name__ == "__main__":
    df = get_sonde_summaries_as_dataframe()
    print(df)
