#!/usr/bin/env bash
#
# setup.sh - install a ka9q-radio + radiosonde_auto_rx receiver on a Raspberry Pi
#            (or any Debian/Raspberry Pi OS box). Generic: pass a station name;
#            nothing site-specific is baked in.
#
#   sudo ./setup.sh <station-name>
#   sudo STATION_LAT=12.345 STATION_LON=-123.456 \
#        UPLOADER_CALLSIGN=N0CALL SONDEHUB_CONTACT_EMAIL=you@example.com \
#        ./setup.sh <station-name>
#
# <station-name> is a short, lowercase, DNS-safe label for THIS receiver (e.g.
# "pirate"). It namespaces radiod's mDNS streams (<name>.local / <name>-pcm.local)
# and the radiod systemd instance (radiod@<name>), so multiple receivers can
# coexist on one LAN without colliding on a shared name like "sonde.local".
#
# Station identity can be supplied with the environment variables above. Keep
# site-specific values out of this repo; pass them at setup time or answer the
# prompts on a fresh interactive run.
#
# Idempotent: completed steps leave markers in /var/lib/sonde-rx and are skipped
# on re-run (handy on slow boards where the build + FFTW wisdom take a long time).
# Env knobs:  FORCE=1 redo a step;  SKIP_WISDOM=1 skip the (very slow) FFTW tuning.

set -euo pipefail

# ---- pinned versions (auto_rx dictates the compatible ka9q-radio commit) --------
KA9Q_REPO=https://github.com/ka9q/ka9q-radio.git
KA9Q_COMMIT=e1224dcd1991637ba8e1caa68cd802e1b22933de
AUTORX_REPO=https://github.com/projecthorus/radiosonde_auto_rx.git
AUTORX_COMMIT=578836651ed5b33d358b4a994e7c7b25ad46ef03    # v1.8.2 (pairs with the ka9q pin)

# ---- install locations ----------------------------------------------------------
KA9Q_SRC=/usr/local/src/ka9q-radio
AUTORX_DIR=/opt/radiosonde_auto_rx
AUTORX_VENV=/opt/auto_rx-venv
STATE_DIR=/var/lib/sonde-rx

# ---- FFTW wisdom transform set radiod needs for the Airspy autorx config --------
# (matches the working Airspy+auto_rx setup; if radiod's startup log shows other
#  sizes, set FFTW_WISDOM_SIZES to match. On small boards this takes HOURS.)
FFTW_WISDOM_SIZES="rof300000 cob2400 cob1250 cob1202 cob1200"

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
sub()  { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }
done_already() { [[ -f "$STATE_DIR/$1.done" && "${FORCE:-0}" != 1 ]]; }
mark_done()    { mkdir -p "$STATE_DIR"; date -Is > "$STATE_DIR/$1.done"; }
station_identity_supplied() {
    [[ -n "${STATION_LAT:-}${STATION_LON:-}${UPLOADER_CALLSIGN:-}${SONDEHUB_CONTACT_EMAIL:-}" ]]
}
prompt_if_missing() {
    local var="$1" label="$2" answer
    [[ -n "${!var:-}" ]] && return 0
    [[ -t 0 ]] || return 0
    read -r -p "$label: " answer
    printf -v "$var" '%s' "$answer"
    export "$var"
}
cfg_set() {
    local cfg="$1" key="$2" value="$3" escaped
    [[ -n "$value" ]] || return 0
    escaped="${value//\\/\\\\}"
    escaped="${escaped//&/\\&}"
    if grep -Eq "^[[:space:]]*${key}[[:space:]]*=" "$cfg"; then
        sed -i -E "s|^[[:space:]]*${key}[[:space:]]*=.*|${key} = ${escaped}|" "$cfg"
    else
        printf '\n%s = %s\n' "$key" "$value" >> "$cfg"
    fi
}
cfg_get() {
    local cfg="$1" key="$2"
    sed -n -E "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*(.*[^[:space:]])[[:space:]]*$/\1/p" "$cfg" | tail -n 1
}
configure_autorx_station_cfg() {
    local cfg="$1" prompt="$2" missing=()
    if [[ "$prompt" == 1 ]]; then
        prompt_if_missing STATION_LAT "Station latitude"
        prompt_if_missing STATION_LON "Station longitude"
        prompt_if_missing UPLOADER_CALLSIGN "Uploader callsign"
        prompt_if_missing SONDEHUB_CONTACT_EMAIL "SondeHub contact email"
    fi

    cfg_set "$cfg" sdr_type KA9Q
    cfg_set "$cfg" sdr_hostname "$MDNS_STATUS"
    cfg_set "$cfg" web_control False
    cfg_set "$cfg" station_lat "${STATION_LAT:-}"
    cfg_set "$cfg" station_lon "${STATION_LON:-}"
    cfg_set "$cfg" uploader_callsign "${UPLOADER_CALLSIGN:-}"
    cfg_set "$cfg" sondehub_contact_email "${SONDEHUB_CONTACT_EMAIL:-}"

    [[ -n "$(cfg_get "$cfg" station_lat)" ]] || missing+=(STATION_LAT)
    [[ -n "$(cfg_get "$cfg" station_lon)" ]] || missing+=(STATION_LON)
    [[ -n "$(cfg_get "$cfg" uploader_callsign)" ]] || missing+=(UPLOADER_CALLSIGN)
    [[ -n "$(cfg_get "$cfg" sondehub_contact_email)" ]] || missing+=(SONDEHUB_CONTACT_EMAIL)
    STATION_CFG_MISSING="${missing[*]:-}"
}
write_radiod_config() {
    install -d -o root -g radio -m 2775 /etc/radio
    cat > "/etc/radio/radiod@${STATION}.conf" <<EOF
# Managed by sonde-search/pirate/setup.sh for station '$STATION'.
# Airspy -> radiosonde_auto_rx, over loopback multicast (local to this box).
[global]
hardware = airspy
mode = fm
status = ${MDNS_STATUS}
iface = lo
ttl = 0
data = ${MDNS_DATA}

[airspy]
device = airspy
description = "${STATION} auto_rx"
# Airspy LO; set >=600 kHz above the highest freq of interest. 407 MHz covers the
# 400-406 MHz radiosonde band on an Airspy R2 (use 405m8 for the narrower Mini).
frequency = 407m0
#bias = true        # uncomment to power a preamp via bias-tee
#gainstep = 17      # uncomment for fixed gain (0-21) instead of AGC

[telemetry]
freq = "401m50"

[manual-400]
freq = 0
ttl = 0
EOF
    chown root:radio "/etc/radio/radiod@${STATION}.conf"

    # loopback multicast must be on (radiod publishes on iface=lo); order radiod after it
    systemctl enable --now set_lo_multicast.service
    mkdir -p "/etc/systemd/system/radiod@${STATION}.service.d"
    cat > "/etc/systemd/system/radiod@${STATION}.service.d/10-lo-multicast.conf" <<EOF
[Unit]
After=set_lo_multicast.service
Wants=set_lo_multicast.service
EOF
}
write_autorx_service() {
    local cfg="$1"
    cat > /etc/systemd/system/auto_rx.service <<EOF
[Unit]
Description=radiosonde_auto_rx ($STATION)
After=network-online.target radiod@${STATION}.service
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$AUTORX_DIR/auto_rx
ExecStart=$AUTORX_VENV/bin/python3 $AUTORX_DIR/auto_rx/auto_rx.py -t 0 -c $cfg
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
}

# ---- args -----------------------------------------------------------------------
[[ $# -eq 1 ]] || die "usage: sudo $0 <station-name>   (short, lowercase, e.g. 'pirate')"
STATION="$1"
[[ "$STATION" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "station name must be lowercase letters/digits/hyphens, e.g. 'pirate'"
[[ $EUID -eq 0 ]] || exec sudo --preserve-env=FORCE,SKIP_WISDOM,STATION_LAT,STATION_LON,UPLOADER_CALLSIGN,SONDEHUB_CONTACT_EMAIL -- "$0" "$@"
# the unprivileged user auto_rx will run as (the invoker of sudo, else 'pi')
RUN_USER="${SUDO_USER:-pi}"
id "$RUN_USER" >/dev/null 2>&1 || die "run user '$RUN_USER' does not exist"

MDNS_STATUS="${STATION}.local"
MDNS_DATA="${STATION}-pcm.local"
# Limit build parallelism on low-RAM boards: 4 parallel gcc can OOM a 512MB Pi Zero.
JOBS=$(nproc); [[ $(free -m | awk '/^Mem:/{print $2}') -lt 1024 ]] && JOBS=2
export DEBIAN_FRONTEND=noninteractive
log "Setting up sonde receiver '$STATION' (radiod@$STATION, mDNS $MDNS_STATUS/$MDNS_DATA), auto_rx as user '$RUN_USER'"

# =================================================================================
# 1. Headless (this is a 24/7 appliance; never boot a desktop)
# =================================================================================
if ! done_already 1-headless; then
    log "[1/5] headless"
    systemctl set-default multi-user.target >/dev/null 2>&1 || true
    systemctl disable --now lightdm 2>/dev/null || true
    mark_done 1-headless
fi

# =================================================================================
# 2. Packages
# =================================================================================
if ! done_already 2-packages; then
    log "[2/5] packages"
    apt-get update -qq
    # ka9q-radio build deps (per the auto_rx wiki) + auto_rx build/runtime deps
    apt-get install -y --no-install-recommends \
        git rsync time avahi-daemon avahi-utils build-essential make gcc \
        airspy libairspy-dev libairspyhf-dev libavahi-client-dev libbsd-dev libfftw3-dev \
        libhackrf-dev libiniparser-dev libncurses5-dev libopus-dev librtlsdr-dev \
        libusb-1.0-0-dev libusb-dev portaudio19-dev libasound2-dev libogg-dev \
        uuid-dev libsamplerate-dev \
        python3-venv python3-pip cmake libsamplerate0 libusb-1.0-0 sox
    systemctl enable --now avahi-daemon 2>/dev/null || true
    mark_done 2-packages
fi
if ! done_already 2-airspy-tools; then
    log "[2b/5] Airspy CLI tools"
    apt-get update -qq
    apt-get install -y --no-install-recommends airspy
    mark_done 2-airspy-tools
fi

# =================================================================================
# 3. ka9q-radio (pinned). `make install` also creates the 'radio' user, installs
#    sysctls (multicast tuning), udev rules, service units, set_lo_multicast, etc.
# =================================================================================
if ! done_already 3-ka9q; then
    log "[3/5] ka9q-radio @ $KA9Q_COMMIT"
    [[ -d "$KA9Q_SRC/.git" ]] || git clone "$KA9Q_REPO" "$KA9Q_SRC"
    git -C "$KA9Q_SRC" fetch --all --tags --prune
    git -C "$KA9Q_SRC" checkout "$KA9Q_COMMIT"
    make -C "$KA9Q_SRC" clean
    make -C "$KA9Q_SRC" -j"$JOBS"
    make -C "$KA9Q_SRC" install
    udevadm control --reload-rules && udevadm trigger
    sysctl --system >/dev/null
    usermod -aG radio "$RUN_USER"
    mark_done 3-ka9q
fi

# =================================================================================
# 4. radiod config (Airspy -> auto_rx over loopback multicast), wisdom, enable
# =================================================================================
if ! done_already 4-radiod; then
    RADIOD_STEP_RAN=1
    log "[4/5] radiod config + wisdom + enable"
    write_radiod_config

    # FFTW wisdom: radiod reads /etc/fftw/wisdomf. Slow to build (HOURS on a Pi Zero);
    # radiod still runs without it, just with higher CPU / slow startup.
    if [[ "${SKIP_WISDOM:-0}" == 1 ]]; then
        warn "SKIP_WISDOM=1 - not generating /etc/fftw/wisdomf (radiod will be slower)"
    elif [[ -s /etc/fftw/wisdomf ]]; then
        sub "/etc/fftw/wisdomf already present (FORCE_WISDOM=1 to regenerate)"
    else
        log "generating FFTW wisdom ($FFTW_WISDOM_SIZES) - SLOW; hours on a small board..."
        mkdir -p /etc/fftw
        # shellcheck disable=SC2086
        time fftwf-wisdom -v -T 1 -o /etc/fftw/wisdomf $FFTW_WISDOM_SIZES \
            || warn "fftwf-wisdom failed; radiod will plan FFTs at startup instead"
        chgrp radio /etc/fftw/wisdomf 2>/dev/null || true
    fi

    systemctl daemon-reload
    systemctl enable "radiod@${STATION}"
    # non-fatal: radiod won't start if the Airspy isn't plugged in yet
    systemctl restart "radiod@${STATION}" \
        || warn "radiod@${STATION} not running yet - check 'journalctl -u radiod@${STATION}' (Airspy attached?)"
    mark_done 4-radiod
fi
if done_already 4-radiod && [[ "${RADIOD_STEP_RAN:-0}" != 1 ]]; then
    log "Reconciling radiod config + service"
    write_radiod_config
    systemctl daemon-reload
    systemctl enable "radiod@${STATION}"
    systemctl restart "radiod@${STATION}" \
        || warn "radiod@${STATION} not running yet - check 'journalctl -u radiod@${STATION}' (Airspy attached?)"
fi

# =================================================================================
# 5. radiosonde_auto_rx (pinned): venv, build demods, deploy unit + station config
# =================================================================================
if ! done_already 5-autorx; then
    AUTORX_STEP_RAN=1
    log "[5/5] radiosonde_auto_rx @ $AUTORX_COMMIT"
    [[ -d "$AUTORX_DIR/.git" ]] || git clone "$AUTORX_REPO" "$AUTORX_DIR"
    git -C "$AUTORX_DIR" fetch --all --tags --prune
    git -C "$AUTORX_DIR" checkout "$AUTORX_COMMIT"
    chown -R "$RUN_USER":"$RUN_USER" "$AUTORX_DIR"

    # python venv (PEP 668-clean) with auto_rx's pinned requirements
    [[ -x "$AUTORX_VENV/bin/python3" ]] || python3 -m venv "$AUTORX_VENV"
    "$AUTORX_VENV/bin/pip" install --upgrade pip wheel
    "$AUTORX_VENV/bin/pip" install -r "$AUTORX_DIR/auto_rx/requirements.txt"
    chown -R "$RUN_USER":"$RUN_USER" "$AUTORX_VENV"

    # build the C demodulators (as the run user, in the checkout)
    sudo -u "$RUN_USER" bash -c "cd '$AUTORX_DIR/auto_rx' && ./build.sh"

    # station config: start from upstream's example, point it at THIS station's
    # KA9Q mDNS stream, and apply station identity from setup inputs/prompts.
    CFG="$AUTORX_DIR/auto_rx/station.cfg"
    if [[ ! -f "$CFG" ]]; then
        cp "$AUTORX_DIR/auto_rx/station.cfg.example" "$CFG"
        STATION_CFG_IS_NEW=1
    fi
    configure_autorx_station_cfg "$CFG" "${STATION_CFG_IS_NEW:-0}"
    chown "$RUN_USER":"$RUN_USER" "$CFG"

    # systemd unit: run under the venv python, after radiod
    write_autorx_service "$CFG"
    systemctl daemon-reload
    systemctl enable auto_rx.service
    mark_done 5-autorx
fi

CFG="$AUTORX_DIR/auto_rx/station.cfg"
if [[ "${AUTORX_STEP_RAN:-0}" != 1 && -f "$CFG" ]]; then
    if station_identity_supplied; then
        log "Updating station config from setup environment"
    else
        log "Reconciling auto_rx config + service"
    fi
    configure_autorx_station_cfg "$CFG" 0
    write_autorx_service "$CFG"
    systemctl daemon-reload
    systemctl enable auto_rx.service
    chown "$RUN_USER":"$RUN_USER" "$CFG"
    STATION_CFG_UPDATED=1
fi

echo
log "Base install complete for station '$STATION'."
if [[ -n "${STATION_CFG_MISSING:-}" ]]; then
    warn "Station config still needs values before auto_rx will upload correctly:"
    sub "  missing: $STATION_CFG_MISSING"
    sub "  re-run with STATION_LAT, STATION_LON, UPLOADER_CALLSIGN, SONDEHUB_CONTACT_EMAIL or edit:"
    sub "  $AUTORX_DIR/auto_rx/station.cfg"
else
    systemctl restart auto_rx.service || true
    [[ "${STATION_CFG_IS_NEW:-0}${STATION_CFG_UPDATED:-0}" == "" ]] || sub "station config populated: $AUTORX_DIR/auto_rx/station.cfg"
fi
sub "radiod:  systemctl status radiod@${STATION}    |  control ${MDNS_STATUS}"
sub "auto_rx: journalctl -u auto_rx -f"
