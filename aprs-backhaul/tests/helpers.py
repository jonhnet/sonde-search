"""Small shared test helpers."""

import aprslib


def parse_info(info: str) -> dict:
    """Wrap an object info-field in a minimal TNC2 line and run it through
    aprslib.parse. Used by tests to verify our encoder produces packets
    aprslib can parse — which is what the cloud gateway actually relies on."""
    return aprslib.parse(f"N0CALL>APRS:{info}")
