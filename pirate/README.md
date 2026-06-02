# pirate — ka9q-radio + radiosonde_auto_rx receiver setup

A generic installer that turns a Raspberry Pi 4 (or any Debian box) into
a [radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx) receiver
fed by [ka9q-radio](https://github.com/ka9q/ka9q-radio) with an Airspy SDR. Nothing
site-specific is baked in — you pass a station name and either provide station
identity variables or answer the setup prompts.

## Usage
```
sudo ./setup.sh <station-name>
```
`<station-name>` is a short, lowercase, DNS-safe label for this receiver (e.g.
`pirate`). It namespaces radiod's mDNS streams as `<name>.local` / `<name>-pcm.local`
and the systemd instance as `radiod@<name>`, so several receivers can share a LAN
without colliding on a single name like `sonde.local`.

On a fresh config, the script prompts for the station identity fields. You can
also provide them non-interactively:
```
sudo STATION_LAT=12.345 STATION_LON=-123.456 \
  UPLOADER_CALLSIGN=N0CALL SONDEHUB_CONTACT_EMAIL=you@example.com \
  ./setup.sh pirate
```
Keep station-specific values as invocation-time environment variables or local
Pi config. Do not hard-code callsigns, email addresses, or coordinates in the
repo.

## What it installs (pinned)
- **ka9q-radio** at commit `e1224dcd…` (the commit auto_rx is tested against — do
  not use newer; upstream warns it breaks compatibility). `make install` also sets
  up the multicast sysctls, udev rules, the `radio` user, and `set_lo_multicast`.
- **radiosonde_auto_rx** at `578836…` (v1.8.2), in a Python venv (PEP 668-clean),
  with its C demodulators built.
- A radiod config (`/etc/radio/radiod@<name>.conf`) for an Airspy covering the
  400–406 MHz sonde band, publishing to auto_rx over **loopback multicast**.
- Headless boot, FFTW wisdom, and both services enabled.

Idempotent (markers in `/var/lib/sonde-rx`). On rerun, expensive build/wisdom
steps are skipped unless forced, while generated radiod/auto_rx config and
systemd units are reconciled from the script. Env knobs: `FORCE=1` redo a step,
`SKIP_WISDOM=1` skip the slow FFTW tuning.

## Verify
```
systemctl status radiod@<station> auto_rx
journalctl -u radiod@<station> -n 80 --no-pager
journalctl -u auto_rx -n 80 --no-pager
airspy_info
```

Healthy logs include radiod discovering the Airspy, importing FFTW wisdom, and
starting the Airspy stream:
```
Dynamically loading airspy hardware driver
Discovered airspy device serial: ...
fftwf_import_system_wisdom() succeeded
airspy running
```

auto_rx should allocate the KA9Q receiver and begin scanning:
```
Task Manager - SDR #KA9Q-01 has been allocated to Scanner.
Scanner (KA9Q <station>.local) - Running frequency scan.
```

## Hardware notes
- **Pi 4 is the intended target** for the Airspy+ka9q path. A Pi Zero 2 W is
  marginal; use the SondeHound RTL-SDR setup there unless you are experimenting.
- **Attaching the Airspy:** boards without a USB-A port (Pi Zero 2 W) need a
  **micro-USB OTG adapter** on the data port, ideally via a **powered USB hub** —
  the Airspy draws ~0.5 A and will brown out a Zero if powered through the board.
- **FFTW wisdom is the long pole.** It's hardware-specific; on the tested Pi 4
  (`Raspberry Pi 4 Model B Rev 1.5`) the full wisdom run took about **113
  minutes** and produced `/etc/fftw/wisdomf`. Use `SKIP_WISDOM=1` for a first
  pass if needed (radiod runs without it, just slower), then generate wisdom once
  you've confirmed the receiver works.
- **Zero 2 W is marginal for the Airspy+ka9q path:** RAM fits (~110 MB stack in
  512 MB), but radiod's FFT needs ~1 of the 4 weak cores in real time. Watch
  `journalctl -u radiod@<name>` for overruns under live decode. If it can't keep
  up, lower the Airspy sample rate / narrow the band in the radiod config.
- **Expected Pi 4 load:** with an Airspy Mini at 12 MS/s, the tested Pi 4 sat
  around load `0.5-0.8`, with `radiod` using roughly a third of one core while
  auto_rx scanned through KA9Q.
