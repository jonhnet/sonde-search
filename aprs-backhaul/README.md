# aprs-backhaul

Two daemons for operating a radiosonde receive site with APRS as the internet-less backhaul.

## Architecture

```
radiosonde_auto_rx ─(UDP 55673 JSON)─> aprs-backhaul-pi ─(KISS/TCP 8001)─> Direwolf ─(DigiRig/radio)─> APRS RF
                                                                                                          │
                                                                                                          ▼
                                                                                                     iGate → APRS-IS
                                                                                                          │
                                                                                aprs-backhaul-cloud ◀─────┘
                                                                                          │
                                                                                          ▼
                                                                              PUT /sondes/telemetry (SondeHub)
```

Each received sonde is beaconed as an APRS Object at most once per `min_interval_sec`
(default 120s). Objects use custom tocall `APZSDH` so the cloud daemon can filter for
them on APRS-IS without needing to subscribe to the firehose. Supplemental data
(frame, SNR, frequency, altitude, type) rides in the comment field.

## Layout

```
pi/       Pi-side gateway (auto_rx UDP -> Direwolf KISS TCP)
cloud/    Cloud-side gateway (APRS-IS -> SondeHub)
lib/      Shared: UDP listener, APRS encoding/parse, AX.25, KISS
tests/    Unit + end-to-end tests
```

## Install and run

Cloud and dev environments install from the repo-root requirements; the
Pi gets a minimal installation from `pi/requirements.txt`.

```bash
# Pi (minimal):
pip install -r aprs-backhaul/pi/requirements.txt
cp aprs-backhaul/pi/config_example.yaml /etc/aprs-backhaul/pi.yaml
# edit /etc/aprs-backhaul/pi.yaml — fill in `callsign` and `ssid`
cp aprs-backhaul/pi/systemd/aprs-backhaul-pi.service /etc/systemd/system/
systemctl enable --now aprs-backhaul-pi

# Cloud (uses repo-root requirements.txt):
pip install -r requirements.txt
cp aprs-backhaul/cloud/config_example.yaml /etc/aprs-backhaul/cloud.yaml
# edit — fill in `aprsis_callsign` and `uploader_callsign`
cp aprs-backhaul/cloud/systemd/aprs-backhaul-cloud.service /etc/systemd/system/
systemctl enable --now aprs-backhaul-cloud
```

## Required auto_rx config

In `station.cfg`, under `[oziplotter]`:

```
payload_summary_enabled = True
payload_summary_port = 55673
```

## Tests

```bash
python3 -m pytest -v
```
