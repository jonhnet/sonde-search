# pirate — ka9q-radio + radiosonde_auto_rx receiver setup

A generic installer that turns a Raspberry Pi 4 (or any Debian box) into an
off-grid, solar-powered
[radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx) receiver
fed by [ka9q-radio](https://github.com/ka9q/ka9q-radio) with an Airspy SDR.
Nothing site-specific is baked in — you pass a station name and either provide
station identity variables or answer the setup prompts.

## Goal: an off-grid, solar-powered receive site

The pirate station is meant to live somewhere with no grid power and no
backhaul beyond what we bring with us — picture a hilltop with a clear sky
view of the launch site. The whole site runs on the sun:

```
solar panel  →  LiFePO4 battery  →  buck converter  →  PiDog2 v0.7  →  Pi 4 + Airspy
```

Sondes launch on a fixed schedule (typically twice a day, around 00 Z and
12 Z), which opens up a tradeoff between coverage and survivability. We could
oversize the panel and battery and run always-on for maximum coverage, but
we'd rather give up a little coverage so the site rides out long stretches of
poor solar irradiance. The plan is to use the
[**PiDog2 v0.7**](https://github.com/djacobow/pidog2) (a Pi power-manager HAT
that gates the 5 V rail with a MOSFET driven by an onboard MCU) as a scheduled
power gate, programmed to bring the Pi up for a window around each expected
launch and cut power in between. A modest panel and a sensible LiFePO4 pack
can then carry the site through bad weather where an always-on receiver with
the same hardware budget would brown out.

**Scope of this repo:** the installer here brings up the radiosonde reception
software stack on the Pi 4 side of that chain (ka9q-radio, `radiod`, auto_rx,
mDNS, multicast, services). Power scheduling lives in the PiDog2 firmware,
not here.

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
- **Pi 4 is the minimum recommended target** for the Airspy + ka9q-radio path.
  See the Pi Zero 2 W test result below for why a smaller board isn't viable here.
- **Attaching the Airspy:** boards without a USB-A port (Pi Zero 2 W) need a
  **micro-USB OTG adapter** on the data port, ideally via a **powered USB hub** —
  the Airspy draws ~0.5 A and will brown out a Zero if powered through the board.
- **FFTW wisdom is the long pole.** It's hardware-specific; on the tested Pi 4
  (`Raspberry Pi 4 Model B Rev 1.5`) the full wisdom run took about **113
  minutes** and produced `/etc/fftw/wisdomf`. Use `SKIP_WISDOM=1` for a first
  pass if needed (radiod runs without it, just slower), then generate wisdom once
  you've confirmed the receiver works.
- **Pi Zero 2 W test result:** we ran this exact installer on a Zero 2 W and
  the receiver never came up. `radiod` started and held the Airspy, but
  `auto_rx`'s tune handshake — the control-channel RPC that asks `radiod` to
  allocate a frequency slot for a sonde decoder — **timed out even at a 30 s
  timeout**, meaning `radiod` was too CPU-bound to service the request. RAM was
  fine (~110 MB resident in 512 MB); the bottleneck is CPU. `radiod` has to FFT
  the full Airspy stream in real time, and the Zero's 4× Cortex-A53 cores at
  1 GHz aren't enough headroom alongside the Airspy USB stream and `auto_rx`'s
  demodulators. The Pi 4's A72 cores handle the same workload comfortably (see
  the Pi 4 load figures below). If you only have a Zero-class board, use the
  RTL-SDR path in [`../sondehound/`](../sondehound/) — it feeds `auto_rx`
  directly from the dongle, skips `radiod` and its wideband FFT entirely, and
  runs comfortably on a Zero 2 W.
- **Expected Pi 4 load:** with an Airspy Mini at 12 MS/s, the tested Pi 4 sat
  around load `0.5-0.8`, with `radiod` using roughly a third of one core while
  auto_rx scanned through KA9Q.
- **Sizing the power path** (see the Goal section above): the Pi does not
  expose reliable total input-power telemetry, so measure the complete deployed
  power path externally when sizing the panel, battery, regulator, and any
  powered USB hub. Include the Airspy and any networking/backhaul hardware in
  that measurement.
