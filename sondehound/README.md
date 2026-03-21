# SondeHound

A portable radiosonde chasing system. A Raspberry Pi Zero W receives
radiosonde telemetry via an RTLSDR dongle and
[radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx),
then forwards it over BLE to an Android app that displays the sonde's
position on a scrollable map with predicted landing path.

## Components

- **Pi BLE Server** (`pi/`) — Python service that listens for auto_rx
  UDP telemetry and exposes it as a BLE GATT service
- **Android App** (`android/`) — Kotlin app using osmdroid for
  OpenStreetMap display, with BLE connectivity, GPS tracking, and
  landing predictions via the CUSF/Tawhiri API
- **Mock Server** (`mock-autorx/`) — Standalone test tool that
  simulates auto_rx or replays a real auto_rx log file

## What You See on the Phone

- Scrollable OpenStreetMap
- Your GPS position
- Sonde position and track history (red line)
- Predicted descent path to landing (magenta dashed line)
- Predicted landing marker
- Bearing and distance from you to the sonde
- Staleness indicator showing age of last received position
- Auto/frequency mode selector for the receiver

## Prerequisites

### Pi

- Raspberry Pi Zero W (or any Pi with Bluetooth)
- RTLSDR or Airspy dongle
- [radiosonde_auto_rx](https://github.com/projecthorus/radiosonde_auto_rx)
  installed and configured
- Python 3.7+
- BlueZ 5.43+

### Android

- Android phone running Android 8.0+ (API 26+)
- BLE support
- GPS

### Build Machine

- Android Studio (for building the APK), or just the Android SDK
  command-line tools
- JDK 17 or 21 (Android Studio bundles one)

## Setup

### Pi

1. Install radiosonde_auto_rx and verify it's receiving sondes.

2. In auto_rx's `station.cfg`, under `[oziplotter]`:
   ```
   payload_summary_enabled = True
   payload_summary_port = 55673
   ozi_update_rate = 1
   ```
   The default `ozi_update_rate` is 5 seconds which is too slow for
   chasing; set it to 1.

3. Install the BLE server dependencies:
   ```bash
   pip3 install dbus-next
   ```

4. Run the BLE server (requires root for BlueZ GATT access):
   ```bash
   sudo python3 pi/sondehound_ble.py
   ```

   The Pi will advertise itself as "SondeHound" over BLE and start
   forwarding any auto_rx telemetry it receives.

### Android App

1. Build the APK:
   ```bash
   cd android
   ./gradlew assembleDebug
   ```
   If Gradle picks up the wrong JDK, set `org.gradle.java.home` in
   `gradle.properties` to point to a JDK 17 or 21 installation.

2. Install on a connected phone:
   ```bash
   adb install app/build/outputs/apk/debug/app-debug.apk
   ```
   Or transfer `app/build/outputs/apk/debug/app-debug.apk` to your
   phone and sideload it.

3. Open SondeHound. It will:
   - Start scanning for a SondeHound BLE device
   - Connect automatically when found
   - Display sonde telemetry as it arrives
   - Fetch landing predictions from the Tawhiri API (requires cell data)

### Testing Without a Real Sonde

Use the mock server to generate fake telemetry:

```bash
# Simulated descending sonde
python3 mock-autorx/mock_autorx.py

# Two sondes, faster updates
python3 mock-autorx/mock_autorx.py --num-sondes 2 --interval 1

# Replay a real auto_rx log file
python3 mock-autorx/mock_autorx.py --replay /path/to/sonde_log.csv
```

The mock server sends UDP packets on port 55673, the same as auto_rx.
Run it on the same machine as `sondehound_ble.py`.

## Architecture

```
┌─────────────┐     UDP/JSON      ┌──────────────┐     BLE      ┌─────────────┐
│ auto_rx     │ ────────────────  │ sondehound   │ ──────────── │ Android app │
│ (RTLSDR)    │    port 55673     │ _ble.py (Pi) │   GATT       │             │
└─────────────┘                   └──────────────┘              └──────┬──────┘
                                                                       │
                                                                       │ HTTPS
                                                                       ▼
                                                                ┌─────────────┐
                                                                │ Tawhiri API │
                                                                │ (SondeHub)  │
                                                                └─────────────┘
```

## BLE Protocol

The Pi advertises a custom GATT service:

| UUID | Description |
|------|-------------|
| `1c98734f-0510-4fa8-b9c9-b9cea7a631b0` | Service |
| `f798a958-831b-46ba-bb3a-11a063c50ebc` | Telemetry (read/notify) — JSON telemetry chunks |
| `b12af15d-0713-4783-bd68-73b07d4b689b` | Command (write) — mode commands from the app |

Telemetry messages are auto_rx PAYLOAD_SUMMARY JSON, enriched with a
`time_epoch` field by the Pi. Messages larger than the BLE MTU are
fragmented into ~180 byte chunks and delimited by newlines.
