# pirate — ka9q-radio + radiosonde_auto_rx receiver setup

A generic installer that turns a Raspberry Pi (or any Debian box) into
a [radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx) receiver
fed by [ka9q-radio](https://github.com/ka9q/ka9q-radio) with an Airspy SDR. Nothing
site-specific is baked in — you pass a station name, and you fill in your own
location/callsign afterward.

## Usage
```
sudo ./setup.sh <station-name>
```
`<station-name>` is a short, lowercase, DNS-safe label for this receiver (e.g.
`pirate`). It namespaces radiod's mDNS streams as `<name>.local` / `<name>-pcm.local`
and the systemd instance as `radiod@<name>`, so several receivers can share a LAN
without colliding on a single name like `sonde.local`.

Then set your location and callsign (left as upstream placeholders) and restart:
```
sudo nano /opt/radiosonde_auto_rx/auto_rx/station.cfg   # station_lat, station_lon, uploader_callsign, sondehub_contact_email
sudo systemctl restart auto_rx
```

## What it installs (pinned)
- **ka9q-radio** at commit `e1224dcd…` (the commit auto_rx is tested against — do
  not use newer; upstream warns it breaks compatibility). `make install` also sets
  up the multicast sysctls, udev rules, the `radio` user, and `set_lo_multicast`.
- **radiosonde_auto_rx** at `578836…` (v1.8.2), in a Python venv (PEP 668-clean),
  with its C demodulators built.
- A radiod config (`/etc/radio/radiod@<name>.conf`) for an Airspy covering the
  400–406 MHz sonde band, publishing to auto_rx over **loopback multicast**.
- Headless boot, FFTW wisdom, and both services enabled.

Idempotent (markers in `/var/lib/sonde-rx`). Env knobs: `FORCE=1` redo a step,
`SKIP_WISDOM=1` skip the slow FFTW tuning.

## Hardware notes (esp. Raspberry Pi Zero 2 W)
- **Attaching the Airspy:** boards without a USB-A port (Pi Zero 2 W) need a
  **micro-USB OTG adapter** on the data port, ideally via a **powered USB hub** —
  the Airspy draws ~0.5 A and will brown out a Zero if powered through the board.
- **FFTW wisdom is the long pole.** It's hardware-specific and on a Pi Zero 2 W can
  take *hours*. Use `SKIP_WISDOM=1` for a first pass (radiod runs without it, just
  slower), then generate wisdom once you've confirmed the receiver works.
- **Zero 2 W is marginal for the Airspy+ka9q path:** RAM fits (~110 MB stack in
  512 MB), but radiod's FFT needs ~1 of the 4 weak cores in real time. Watch
  `journalctl -u radiod@<name>` for overruns under live decode. If it can't keep
  up, lower the Airspy sample rate / narrow the band in the radiod config.
