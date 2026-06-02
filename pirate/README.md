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
  We tested this exact installer on a Pi Zero 2 W and the receiver never came
  up: `radiod` started and held the Airspy, but `auto_rx`'s tune handshake —
  the control-channel RPC that asks `radiod` to allocate a frequency slot for a
  sonde decoder — **timed out even at a 30 s timeout**, meaning `radiod` was
  too CPU-bound to service the request. RAM was fine (~110 MB resident in
  512 MB); the bottleneck is CPU. `radiod` has to FFT the full Airspy stream in
  real time, and the Zero's 4× Cortex-A53 cores at 1 GHz aren't enough
  headroom alongside the Airspy USB stream and `auto_rx`'s demodulators. The
  Pi 4's A72 cores handle the same workload comfortably (load ~0.5–0.8, radiod
  using roughly a third of one core). If you only have a Zero-class board, use
  the RTL-SDR path in [`../sondehound/`](../sondehound/) — it feeds `auto_rx`
  directly from the dongle, skips `radiod` and its wideband FFT entirely, and
  runs comfortably on a Zero 2 W.
- **FFTW wisdom is the long pole.** It's hardware-specific; on the tested Pi 4
  (`Raspberry Pi 4 Model B Rev 1.5`) the full wisdom run took about **113
  minutes** and produced `/etc/fftw/wisdomf`. Use `SKIP_WISDOM=1` for a first
  pass if needed (radiod runs without it, just slower), then generate wisdom once
  you've confirmed the receiver works.
- **Sizing the power path** (see the Goal section above): the Pi does not
  expose reliable total input-power telemetry, so measure the complete deployed
  power path externally when sizing the panel, battery, regulator, and any
  powered USB hub. Include the Airspy and any networking/backhaul hardware in
  that measurement.

## Solar power budget

### Measured panel output (50 W panel, Seattle, March 2026)

South-facing panel at roughly 45° inclination. Data collected at 1 Hz using a
GW Instek GPP-4323 as a programmable load, logged via SCPI over USB. Collection
and analysis code is in [`../analyzers/paneltest/`](../analyzers/paneltest/).

| Date       | Energy (Wh) | Peak power (W) | Samples |
|------------|-------------|-----------------|---------|
| 2026-03-30 | 90          | —               | —       |
| 2026-03-29 | 18.5        | 22.0            | 85,705  |
| 2026-03-28 | 111.9       | 36.2            | 85,455  |
| 2026-03-27 | 166.6       | 30.5            | 85,637  |
| 2026-03-26 | 149.4       | 33.6            | 85,494  |
| 2026-03-25 | 52.1        | 27.0            | 85,394  |
| 2026-03-24 | 19.1        | 17.5            | 85,340  |
| 2026-03-23 | 67.6        | 22.7            | 85,412  |

**8-day average: ~84 Wh/day.** Best day 167 Wh, worst 18.5 Wh — a 9:1 ratio
within a single week. Peak power never exceeded 36 W from a 50 W panel,
expected for Seattle latitude and non-optimal tilt.

### Seasonal projection

March is below Seattle's annual solar average. Using NREL GHI data for Seattle
(July peak 6.5 kWh/m²/day, December trough 0.7 kWh/m²/day) to scale from the
measured March average of 84 Wh/day:

| Month | Relative irradiance | Est. daily yield (Wh) | Daily surplus/deficit vs. 40 Wh load |
|-------|--------------------:|----------------------:|-------------------------------------:|
| Jan   | 0.33×               | 28                    | −12                                  |
| Feb   | 0.60×               | 50                    | +10                                  |
| **Mar** | **1.00×**          | **84 (measured)**     | **+44**                              |
| Apr   | 1.40×               | 118                   | +78                                  |
| May   | 1.77×               | 148                   | +108                                 |
| Jun   | 1.93×               | 162                   | +122                                 |
| Jul   | 2.17×               | 182                   | +142                                 |
| Aug   | 1.83×               | 154                   | +114                                 |
| Sep   | 1.33×               | 112                   | +72                                  |
| Oct   | 0.77×               | 65                    | +25                                  |
| Nov   | 0.40×               | 34                    | −6                                   |
| Dec   | 0.23×               | 20                    | −20                                  |

The system runs a daily deficit only November through January. December is the
hardest month: ~20 Wh/day average production against a 40 Wh/day load, for a
~20 Wh/day shortfall. Multi-day overcast stretches can push production well
below even that average (possibly 5–10 Wh on a heavily overcast short day).

### Battery sizing for winter survivability

With the PiDog2's voltage-check-on-wake, the station degrades gracefully —
it skips launch windows when the battery is low rather than browning out. The
battery doesn't need to guarantee uninterrupted operation; it needs to keep
the station alive long enough for the next sunny day to recharge it. Battery
sizing therefore determines how many consecutive bad days the station can
ride out before going silent.

Days of autonomy at 40 Wh/day load with zero solar input:

| Battery        | Usable capacity | Days of autonomy |
|----------------|----------------:|-----------------:|
| 10 Ah, 12 V    | 120 Wh          | 3                |
| 20 Ah, 12 V    | 240 Wh          | 6                |
| 30 Ah, 12 V    | 360 Wh          | 9                |
| 50 Ah, 12 V    | 600 Wh          | 15               |

In practice, December days aren't *zero* solar — even the worst days produce
some charge. A 20–30 Ah LiFePO4 battery should carry the station through all
but the worst winter weather, with the PiDog2 gracefully shedding load during
extended overcast stretches.

### Estimated daily load

| Component              | Power   | Daily hours | Daily Wh |
|------------------------|---------|-------------|----------|
| Pi 4 + Airspy (active) | ~8 W    | 4           | 32       |
| SIM7600G-H LTE modem   | ~2 W    | 4           | 8        |
| PiDog2 standby         | ~0.02 W | 20          | 0.4      |
| **Total**              |         |             | **~40 Wh** |

Against the measured solar average of 84 Wh/day, the system banks ~44 Wh/day
surplus on an average March day. See the seasonal projection and battery sizing
tables above for winter survivability analysis.

The PiDog2 reads battery voltage via ADC on wake. If the battery is too low,
the Pi sets a short watchdog timer and shuts back down — gracefully skipping a
launch window rather than draining the battery to the point of a brownout or
corrupted SD card.

## Cellular backhaul

A [**Waveshare SIM7600G-H 4G dongle**](https://www.amazon.com/dp/B09VFKCXHX)
(~$77) provides LTE connectivity. It presents as a USB modem on Linux via
ModemManager (QMI/ECM mode), providing a full IP stack — WireGuard, SSH, and
normal networking all work.

The SIM7600G-H uses a SIMCom module with a Qualcomm MDM9x07 baseband. It was
chosen over the Quectel EC25 (used by the Sixfab Pi ecosystem) primarily for
retail availability: SIMCom modules ship in ready-to-use USB form factors from
Waveshare on Amazon, while EC25 modules are mostly sold as bare mini-PCIe
cards through industrial distributors. Both are Cat 4 LTE and functionally
interchangeable at the Linux USB level.

The dongle includes an external LTE antenna and has a connector for a
higher-gain antenna — important because the modem will be inside a sealed
weatherproof enclosure.

**Data plan:** [Hologram](https://hologram.io) IoT SIM at $0.03/MB +
$1/month per SIM. Auto_rx uploads are a few KB/sec per active sonde.
WireGuard keepalives (`PersistentKeepalive=25`) add ~2 MB/month during the
4 h/day active window. Total monthly data is well under 100 MB. Expected
operating cost: **~$3–5/month**.

**Remote access:** a persistent WireGuard tunnel to a VPS provides inbound
SSH without dealing with carrier NAT or port forwarding.

## Bill of materials

| Item                                  | Approx. cost |
|---------------------------------------|-------------|
| Raspberry Pi 4 (2 GB+)               | $45         |
| Airspy Mini                           | $100        |
| Waveshare SIM7600G-H 4G dongle       | $77         |
| PiDog2 power manager                 | —           |
| 50 W solar panel                      | $50–75      |
| MPPT charge controller (small)        | $20–30      |
| LiFePO4 battery (20–30 Ah, 12 V)     | $50–80      |
| 403 MHz antenna                       | $20–40      |
| LTE antenna (external, for enclosure) | $10–15      |
| Weatherproof enclosure                | $30–50      |
| Hologram SIM card                     | $3          |
| **Total**                             | **~$400–500** |

Monthly operating cost: ~$3–5 (Hologram cellular).
