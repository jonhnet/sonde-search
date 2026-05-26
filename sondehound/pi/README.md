# SondeHound Pi provisioning

`setup.sh` turns a low-power board (e.g. Raspberry Pi Zero 2 W) into a portable
SondeHound receiver. It automates the manual "Setup → Pi" steps in the top-level
[SondeHound README](../README.md).

```
sudo ./setup.sh
```

An RTL-SDR dongle feeding auto_rx directly is a lightweight receive path that runs
comfortably on a Zero-class board. For a higher-sensitivity Airspy receiver on a
more capable board (e.g. a Pi 4), see the sibling [`pirate/`](../../pirate/) setup.

Installs and configures, as systemd services:

1. **radiosonde_auto_rx** (pinned) driving an **RTL-SDR** dongle directly — a
   lightweight receive path that runs comfortably on a Zero-class board.
2. **auto_rx config** tuned for the portable use case:
   - `sdr_type = RTLSDR`
   - `sondehub_enabled = False` — **local-only**, no upload (you're often off-grid
     while chasing; the phone fetches predictions itself)
   - `payload_summary_enabled = True`, `payload_summary_port = 55673`,
     `ozi_update_rate = 1` — the UDP telemetry feed the BLE bridge consumes
   - `web_control = False`. (auto_rx has no switch to disable its Flask web server,
     so it still runs (~15 MB idle); harmless on a headless node, left as-is.)
3. **`sondehound-ble.service`** — runs `sondehound_ble.py`, relaying that UDP
   telemetry to the Android app over BLE (advertises as "SondeHound").

Then set your location/callsign (left as upstream placeholders) and restart:
```
sudo nano /opt/radiosonde_auto_rx/auto_rx/station.cfg   # station_lat, station_lon, uploader_callsign; check rtlsdr_device_idx, gain, ppm
sudo systemctl restart auto_rx sondehound-ble
```

Watch: `journalctl -u auto_rx -f` and `journalctl -u sondehound-ble -f`.

Idempotent (markers in `/var/lib/sonde-rx`); `FORCE=1` redoes a step. Hardware note:
the RTL-SDR plugs into the Zero 2 W's USB OTG port via a micro-USB-OTG adapter
(no powered hub needed — an RTL-SDR sips power, unlike the Airspy).
