"""Shared utilities for processing sonde data."""

import pandas as pd

# Identify ourselves to external services. Keep it stable and specific: OSM
# blocks generic or per-run-random User-Agents (contextily's default) outright.
USER_AGENT = "sonde-search (+https://github.com/jonhnet/sonde-search)"

# Minimum peak altitude (meters) to be considered a real flight.
# Rejects ground-based transmitters and bench tests.
MIN_MAX_ALT = 5000

# Minimum altitude drop (meters) from peak to final position.
# Rejects sondes that are still ascending.
MIN_ALT_DROP = 500


def filter_real_flights(df):
    """Filter a sonde DataFrame to only include real flights.

    A real flight is one where:
    - The sonde reached at least MIN_MAX_ALT meters altitude
    - The final altitude is at least MIN_ALT_DROP meters below the peak
      (i.e., the sonde has started descending)

    Args:
        df: DataFrame with at least 'serial', 'frame', and 'alt' columns.
            May contain multiple rows per sonde (multiple telemetry frames).

    Returns:
        DataFrame containing only rows belonging to real flights.
    """
    if df.empty:
        return df

    # Drop NA frame/alt rows; an all-NA 'frame' group would crash idxmax().
    usable = df.dropna(subset=["frame", "alt"])
    if usable.empty:
        return df.iloc[:0]

    grouped = usable.groupby("serial")
    max_alt = grouped["alt"].max()
    final_alt = grouped.apply(lambda g: g.loc[g["frame"].idxmax(), "alt"], include_groups=False)

    valid_serials = max_alt.index[(max_alt >= MIN_MAX_ALT) & (final_alt <= max_alt - MIN_ALT_DROP)]
    return df[df["serial"].isin(valid_serials)]


def get_landing_rows(df):
    """Reduce a multi-row-per-sonde DataFrame to one row per sonde: the landing.

    The landing row is the one with the highest frame number for each serial,
    which is the last telemetry point received.

    Args:
        df: DataFrame with at least 'serial' and 'frame' columns.

    Returns:
        DataFrame with one row per sonde.
    """
    if df.empty:
        return df

    # Drop NA-frame rows; an all-NA 'frame' group would crash idxmax().
    usable = df.dropna(subset=["frame"])
    if usable.empty:
        return df.iloc[:0]

    return df.loc[usable.groupby("serial")["frame"].idxmax()]


def parse_sondehub_datetimes(values):
    """Parse SondeHub ISO8601 timestamps into tz-aware UTC datetimes.

    SondeHub telemetry mixes timestamp precision between uploaders. Most emit
    fractional seconds ("2026-08-20T10:29:59.005000Z"), but some -- SondeFox
    0.12.1, for one -- omit them ("2026-08-20T12:21:59Z"). Bare pd.to_datetime()
    infers a single format from the first element and then applies it strictly
    to every other element, so one odd record among thousands raises ValueError
    and takes down the whole batch.

    format="ISO8601" accepts any valid ISO8601 spelling, so mixed precision
    parses cleanly. utc=True guarantees a real datetime64 column rather than an
    object column of mixed-offset Timestamps, should an uploader ever send an
    offset other than Z.

    Args:
        values: A scalar, list, or Series of ISO8601 timestamp strings. Values
            that are already datetime64 pass through unchanged.

    Returns:
        The same shape as the input, as tz-aware UTC datetimes.
    """
    return pd.to_datetime(values, format="ISO8601", utc=True)
