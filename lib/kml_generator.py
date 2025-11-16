"""
KML file generator for radiosonde flight paths.
"""

import pandas as pd
import simplekml
import sondehub


# Given a sonde serial number, generate a KML file.
def generate_kml(serial: str) -> str:
    # Fetch sonde data from SondeHub
    sonde_data = sondehub.download(serial=serial)
    sonde = pd.DataFrame(sonde_data)

    if sonde.empty:
        raise ValueError(f"Sonde {serial} does not exist or has no data")

    # Convert datetime column to pandas datetime
    sonde['datetime'] = pd.to_datetime(sonde['datetime'])

    # Index by datetime and drop all columns other than lat, lon, alt
    sonde = sonde.set_index('datetime')[['lon', 'lat', 'alt']]

    # For each minute, take the last location a sonde was seen during that
    # minute. Also add the very first sonde sighting, and the highest
    # altitude point. Note for the highest point we take head(1) in case
    # there are multiple reports at that highest altitude. We pass a list
    # to sonde.loc[] to ensure we get a dataframe back from loc, not a series,
    # in case the label is unique.
    by_minute = pd.concat([
        sonde.head(1),
        sonde.resample('1 min', label='right').last(),
        sonde.loc[[sonde['alt'].idxmax()]].head(1),
    ]).dropna().sort_index()

    # Create KML document
    kml = simplekml.Kml()
    kml.document.name = serial
    linestring = kml.newlinestring(name=serial)
    linestring.coords = list(by_minute.itertuples(index=False, name=None))  # type: ignore[assignment]
    linestring.altitudemode = simplekml.AltitudeMode.absolute  # type: ignore[assignment]
    linestring.extrude = 1  # type: ignore[assignment]
    linestring.style.linestyle.color = simplekml.Color.red
    linestring.style.linestyle.width = 5

    return kml.kml()
