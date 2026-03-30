"""Shared utilities for processing sonde data."""

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

    grouped = df.groupby('serial')
    max_alt = grouped['alt'].max()
    final_alt = grouped.apply(
        lambda g: g.loc[g['frame'].idxmax(), 'alt'], include_groups=False
    )

    valid_serials = max_alt.index[
        (max_alt >= MIN_MAX_ALT) & (final_alt <= max_alt - MIN_ALT_DROP)
    ]
    return df[df['serial'].isin(valid_serials)]
