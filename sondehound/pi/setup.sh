#!/usr/bin/env bash
#
# setup.sh - provision the SondeHound portable Pi receiver.
#
# Sets up the lightweight RX path for a low-power board (e.g. Raspberry Pi
# Zero 2 W): radiosonde_auto_rx driving an RTL-SDR dongle directly, configured
# to emit PAYLOAD_SUMMARY telemetry over UDP :55673, and the sondehound_ble.py
# BLE bridge that relays it to the Android app. Both run as systemd services.
#
#   sudo ./setup.sh
#
# Generic; nothing site-specific is baked in. After it runs, edit the
# station config (lat/lon/callsign) - the script prints the path - and restart
# auto_rx. Idempotent (markers in /var/lib/sonde-rx); FORCE=1 redoes a step.

set -euo pipefail

AUTORX_REPO=https://github.com/projecthorus/radiosonde_auto_rx.git
AUTORX_COMMIT=578836651ed5b33d358b4a994e7c7b25ad46ef03   # v1.8.2
AUTORX_DIR=/opt/radiosonde_auto_rx
AUTORX_VENV=/opt/auto_rx-venv
BLE_VENV=/opt/sondehound-ble-venv
BLE_DEST=/opt/sondehound
UDP_PORT=55673                 # auto_rx PAYLOAD_SUMMARY -> sondehound_ble.py
STATE_DIR=/var/lib/sonde-rx
SELF="$(cd "$(dirname "$0")" && pwd)"
BLE_SRC="$SELF/sondehound_ble.py"       # the BLE bridge, alongside this script in pi/

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
sub()  { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }
done_already() { [[ -f "$STATE_DIR/$1.done" && "${FORCE:-0}" != 1 ]]; }
mark_done()    { mkdir -p "$STATE_DIR"; date -Is > "$STATE_DIR/$1.done"; }

[[ $EUID -eq 0 ]] || exec sudo --preserve-env=FORCE -- "$0" "$@"
RUN_USER="${SUDO_USER:-pi}"
id "$RUN_USER" >/dev/null 2>&1 || die "run user '$RUN_USER' does not exist"
[[ -f "$BLE_SRC" ]] || die "BLE bridge not found at $BLE_SRC (run from sondehound/pi/)"
export DEBIAN_FRONTEND=noninteractive
log "Provisioning SondeHound portable receiver (auto_rx as '$RUN_USER', BLE bridge as root)"

# =================================================================================
# 1. Headless
# =================================================================================
if ! done_already 1-headless; then
    log "[1/5] headless"
    systemctl set-default multi-user.target >/dev/null 2>&1 || true
    systemctl disable --now lightdm 2>/dev/null || true
    mark_done 1-headless
fi

# =================================================================================
# 2. Packages: RTL-SDR + auto_rx build deps + BlueZ (for the BLE bridge)
# =================================================================================
if ! done_already 2-packages; then
    log "[2/5] packages"
    apt-get update -qq
    apt-get install -y --no-install-recommends \
        git rsync rtl-sdr librtlsdr-dev libusb-1.0-0-dev sox \
        build-essential cmake python3-venv python3-pip bluez
    # kernel DVB-T driver grabs RTL2832 dongles; blacklist so rtl-sdr can claim it
    cat > /etc/modprobe.d/rtl-sdr-blacklist.conf <<'EOF'
blacklist dvb_usb_rtl28xxu
blacklist rtl2832
blacklist rtl2830
EOF
    rmmod dvb_usb_rtl28xxu 2>/dev/null || true
    # Auto-power the BT adapter at boot. On a Zero the onboard adapter otherwise
    # comes up DOWN, and the BLE bridge can't power it (its Powered=True fails).
    install -d /etc/bluetooth
    if ! grep -qE '^[[:space:]]*AutoEnable[[:space:]]*=[[:space:]]*true' /etc/bluetooth/main.conf 2>/dev/null; then
        if grep -qiE '^[[:space:]]*#?[[:space:]]*AutoEnable[[:space:]]*=' /etc/bluetooth/main.conf 2>/dev/null; then
            sed -i -E 's/^[[:space:]]*#?[[:space:]]*AutoEnable[[:space:]]*=.*/AutoEnable=true/' /etc/bluetooth/main.conf
        else
            printf '\n[Policy]\nAutoEnable=true\n' >> /etc/bluetooth/main.conf
        fi
    fi
    systemctl enable bluetooth 2>/dev/null || true
    systemctl restart bluetooth 2>/dev/null || true
    mark_done 2-packages
fi

# =================================================================================
# 3. radiosonde_auto_rx (pinned): clone, build demods, venv
# =================================================================================
if ! done_already 3-autorx-build; then
    log "[3/5] radiosonde_auto_rx @ $AUTORX_COMMIT"
    [[ -d "$AUTORX_DIR/.git" ]] || git clone "$AUTORX_REPO" "$AUTORX_DIR"
    git -C "$AUTORX_DIR" fetch --all --tags --prune
    git -C "$AUTORX_DIR" checkout "$AUTORX_COMMIT"
    chown -R "$RUN_USER":"$RUN_USER" "$AUTORX_DIR"
    [[ -x "$AUTORX_VENV/bin/python3" ]] || python3 -m venv "$AUTORX_VENV"
    "$AUTORX_VENV/bin/pip" install --upgrade pip wheel
    "$AUTORX_VENV/bin/pip" install -r "$AUTORX_DIR/auto_rx/requirements.txt"
    chown -R "$RUN_USER":"$RUN_USER" "$AUTORX_VENV"
    sudo -u "$RUN_USER" bash -c "cd '$AUTORX_DIR/auto_rx' && ./build.sh"
    mark_done 3-autorx-build
fi

# =================================================================================
# 4. auto_rx config (RTL-SDR + PAYLOAD_SUMMARY -> UDP for the BLE bridge) + service
# =================================================================================
if ! done_already 4-autorx-svc; then
    log "[4/5] auto_rx config + service"
    CFG="$AUTORX_DIR/auto_rx/station.cfg"
    if [[ ! -f "$CFG" ]]; then
        cp "$AUTORX_DIR/auto_rx/station.cfg.example" "$CFG"
        # RTL-SDR backend; local-only (no SondeHub upload - portable/no-internet);
        # PAYLOAD_SUMMARY UDP feed on for the BLE bridge at a 1s rate.
        # NB: auto_rx has no switch to disable its Flask web server, so it still
        # runs (~15MB idle); harmless on a headless node, left as-is.
        sed -i \
            -e "s/^sdr_type *=.*/sdr_type = RTLSDR/" \
            -e "s/^sondehub_enabled *=.*/sondehub_enabled = False/" \
            -e "s/^web_control *=.*/web_control = False/" \
            -e "s/^payload_summary_enabled *=.*/payload_summary_enabled = True/" \
            -e "s/^payload_summary_port *=.*/payload_summary_port = ${UDP_PORT}/" \
            -e "s/^ozi_update_rate *=.*/ozi_update_rate = 1/" \
            "$CFG"
        chown "$RUN_USER":"$RUN_USER" "$CFG"
        CFG_IS_NEW=1
    fi
    cat > /etc/systemd/system/auto_rx.service <<EOF
[Unit]
Description=radiosonde_auto_rx (RTL-SDR, SondeHound)
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$AUTORX_DIR/auto_rx
ExecStart=$AUTORX_VENV/bin/python3 $AUTORX_DIR/auto_rx/auto_rx.py -t 0 -c $CFG
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable auto_rx.service
    mark_done 4-autorx-svc
fi

# =================================================================================
# 5. SondeHound BLE bridge (auto_rx UDP -> BLE GATT -> Android). Needs root/BlueZ.
# =================================================================================
if ! done_already 5-ble; then
    log "[5/5] BLE bridge"
    install -d "$BLE_DEST"
    install -m 0755 "$BLE_SRC" "$BLE_DEST/sondehound_ble.py"
    [[ -x "$BLE_VENV/bin/python3" ]] || python3 -m venv "$BLE_VENV"
    "$BLE_VENV/bin/pip" install --upgrade pip wheel
    "$BLE_VENV/bin/pip" install -r "$SELF/requirements.txt"   # dbus-next
    cat > /etc/systemd/system/sondehound-ble.service <<EOF
[Unit]
Description=SondeHound BLE bridge (auto_rx UDP :${UDP_PORT} -> BLE GATT)
After=bluetooth.service auto_rx.service
Wants=bluetooth.service

[Service]
ExecStart=$BLE_VENV/bin/python3 $BLE_DEST/sondehound_ble.py --udp-port ${UDP_PORT}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable sondehound-ble.service
    mark_done 5-ble
fi

echo
log "SondeHound base install complete."
if [[ "${CFG_IS_NEW:-0}" == 1 ]]; then
    warn "EDIT YOUR STATION CONFIG before auto_rx will upload/predict correctly:"
    sub "  $AUTORX_DIR/auto_rx/station.cfg   (station_lat, station_lon, uploader_callsign, sondehub_contact_email)"
    sub "  RTL-SDR knobs to check: rtlsdr_device_idx, gain, ppm"
    sub "then: sudo systemctl restart auto_rx sondehound-ble"
else
    systemctl restart auto_rx.service sondehound-ble.service || true
fi
sub "auto_rx:  journalctl -u auto_rx -f"
sub "BLE:      journalctl -u sondehound-ble -f   (advertises as 'SondeHound')"
