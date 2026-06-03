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
#   sudo LTE_APN=your.apn ./setup.sh <station-name>
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
#             SONDEHUB_UPLOAD_RATE controls SondeHub batch upload cadence.
#             LTE_APN/LTE_USERNAME/LTE_PASSWORD/LTE_PIN configure cellular backhaul.

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
    cfg_set "$cfg" sondehub_upload_rate "${SONDEHUB_UPLOAD_RATE:-60}"

    [[ -n "$(cfg_get "$cfg" station_lat)" ]] || missing+=(STATION_LAT)
    [[ -n "$(cfg_get "$cfg" station_lon)" ]] || missing+=(STATION_LON)
    [[ -n "$(cfg_get "$cfg" uploader_callsign)" ]] || missing+=(UPLOADER_CALLSIGN)
    [[ -n "$(cfg_get "$cfg" sondehub_contact_email)" ]] || missing+=(SONDEHUB_CONTACT_EMAIL)
    STATION_CFG_MISSING="${missing[*]:-}"
}
configure_lte_backhaul() {
    local name="${LTE_CONNECTION_NAME:-pirate-lte}"

    systemctl enable --now ModemManager.service 2>/dev/null || true
    udevadm control --reload-rules

    # If the modem was already plugged in before ModemManager's udev rules were
    # installed, retrigger the actual child devices so MM sees the QMI/AT ports.
    local sys
    for sys in /sys/class/tty/ttyUSB* /sys/class/usbmisc/cdc-wdm* /sys/class/net/wwan*; do
        [[ -e "$sys" ]] || continue
        udevadm trigger --action=change "$sys" 2>/dev/null || true
    done
    udevadm settle 2>/dev/null || true

    [[ -n "${LTE_APN:-}" ]] || {
        sub "cellular modem support installed; set LTE_APN to create a NetworkManager GSM connection"
        return 0
    }

    command -v nmcli >/dev/null 2>&1 || {
        warn "nmcli not found; LTE_APN was set but NetworkManager is not available"
        return 0
    }

    if nmcli -t -f NAME connection show | grep -Fxq "$name"; then
        nmcli connection modify "$name" gsm.apn "$LTE_APN"
    else
        nmcli connection add type gsm ifname "*" con-name "$name" apn "$LTE_APN"
    fi
    nmcli connection modify "$name" connection.autoconnect yes connection.metered yes ipv4.method auto ipv6.method auto
    [[ -z "${LTE_USERNAME:-}" ]] || nmcli connection modify "$name" gsm.username "$LTE_USERNAME"
    [[ -z "${LTE_PASSWORD:-}" ]] || nmcli connection modify "$name" gsm.password "$LTE_PASSWORD"
    [[ -z "${LTE_PIN:-}" ]] || nmcli connection modify "$name" gsm.pin "$LTE_PIN"

    # SIM7600 can retain an unrelated initial EPS bearer APN in modem firmware
    # (e.g. CMNET). LTE registration/data attach may not complete until this
    # matches the SIM provider APN.
    if command -v mmcli >/dev/null 2>&1 && mmcli -m any >/dev/null 2>&1; then
        mmcli -m any --3gpp-set-initial-eps-bearer-settings="apn=${LTE_APN},ip-type=ipv4" \
            || warn "could not set initial EPS bearer APN; NetworkManager APN is still configured"
    fi
    sub "cellular NetworkManager connection configured: $name"
}
configure_backhaul_cost_controls() {
    log "Reconciling backhaul cost controls"
    apt-get purge -y unattended-upgrades 2>/dev/null || true
    apt-get autoremove -y 2>/dev/null || true
    systemctl disable --now apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
    systemctl disable --now apt-daily.service apt-daily-upgrade.service 2>/dev/null || true

    cat > /etc/apt/apt.conf.d/10pirate-no-periodic <<'EOF'
APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
APT::Periodic::AutocleanInterval "0";
EOF

    cat > /usr/local/sbin/pirate-apt-backhaul-guard <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

[[ "${ALLOW_EXPENSIVE_BACKHAUL:-0}" == 1 ]] && exit 0

default_dev="$(ip -o route show default 2>/dev/null | awk '{for (i=1; i<=NF; i++) if ($i == "dev") {print $(i+1); exit}}')"
case "$default_dev" in
    wwan*|cdc-wdm*|ppp*)
        printf '%s\n' "APT blocked: default route is on $default_dev. Set ALLOW_EXPENSIVE_BACKHAUL=1 to override." >&2
        exit 100
        ;;
esac
EOF
    chmod 0755 /usr/local/sbin/pirate-apt-backhaul-guard

    cat > /etc/apt/apt.conf.d/99pirate-backhaul-guard <<'EOF'
APT::Update::Pre-Invoke { "/usr/local/sbin/pirate-apt-backhaul-guard"; };
DPkg::Pre-Invoke { "/usr/local/sbin/pirate-apt-backhaul-guard"; };
EOF
}
configure_avahi_backhaul_policy() {
    log "Reconciling Avahi backhaul policy"

    [[ -f /etc/avahi/avahi-daemon.conf ]] || return 0

    if grep -Eq '^[#[:space:]]*allow-interfaces=' /etc/avahi/avahi-daemon.conf; then
        sed -i -E 's|^[#[:space:]]*allow-interfaces=.*|allow-interfaces=lo,wlan0|' /etc/avahi/avahi-daemon.conf
    else
        sed -i '/^\[server\]/a allow-interfaces=lo,wlan0' /etc/avahi/avahi-daemon.conf
    fi

    if grep -Eq '^[#[:space:]]*enable-wide-area=' /etc/avahi/avahi-daemon.conf; then
        sed -i -E 's|^[#[:space:]]*enable-wide-area=.*|enable-wide-area=no|' /etc/avahi/avahi-daemon.conf
    else
        sed -i '/^\[wide-area\]/a enable-wide-area=no' /etc/avahi/avahi-daemon.conf
    fi

    systemctl enable --now avahi-daemon.service 2>/dev/null || true
    systemctl restart avahi-daemon.service 2>/dev/null || true
}
configure_mdns_resolver_policy() {
    log "Reconciling mDNS resolver policy"

    cat > /etc/mdns.allow <<'EOF'
.local.
.local
EOF

    if [[ -f /etc/nsswitch.conf ]] && grep -Eq '^hosts:' /etc/nsswitch.conf; then
        # mdns4_minimal checks unicast DNS for "SOA local" before .local lookups.
        # mdns4 honors /etc/mdns.allow, which lets .local stay local-only.
        sed -i -E '/^hosts:/ s/\bmdns4_minimal\b/mdns4/g' /etc/nsswitch.conf
    fi
}
configure_multicast_backhaul_policy() {
    log "Reconciling cellular multicast policy"

    cat > /usr/local/sbin/pirate-multicast-policy <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

# Generic multicast policy for a remote sensor:
# - WiFi may carry multicast/mDNS when available.
# - Loopback is the fallback for local-only multicast.
# - Cellular/WWAN must never be eligible for multicast egress.

ip link set lo multicast on 2>/dev/null || true
ip route replace 224.0.0.0/4 dev lo src 127.0.0.1 metric 1000
ip -6 route replace ff00::/8 dev lo metric 1000 2>/dev/null || true

for dev in /sys/class/net/wlan*; do
    [[ -e "$dev" ]] || continue
    ifname=${dev##*/}
    ip link show dev "$ifname" >/dev/null 2>&1 || continue
    ip route replace 224.0.0.0/4 dev "$ifname" metric 100 2>/dev/null || true
    ip -6 route replace ff00::/8 dev "$ifname" metric 100 2>/dev/null || true
done

for dev in /sys/class/net/wwan* /sys/class/net/ppp*; do
    [[ -e "$dev" ]] || continue
    ifname=${dev##*/}
    ip link set dev "$ifname" multicast off 2>/dev/null || true
done
EOF
    chmod 0755 /usr/local/sbin/pirate-multicast-policy

    install -d -m 0755 /etc/NetworkManager/dispatcher.d
    cat > /etc/NetworkManager/dispatcher.d/90-pirate-multicast-policy <<'EOF'
#!/usr/bin/env bash
exec /usr/local/sbin/pirate-multicast-policy
EOF
    chmod 0755 /etc/NetworkManager/dispatcher.d/90-pirate-multicast-policy

    cat > /usr/local/sbin/pirate-backhaul-firewall <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

command -v nft >/dev/null 2>&1 || {
    echo "nft not installed; cannot enforce cellular multicast firewall" >&2
    exit 1
}

nft delete table inet pirate_backhaul 2>/dev/null || true
nft -f - <<'NFT'
table inet pirate_backhaul {
    chain output {
        type filter hook output priority filter; policy accept;

        # Cellular backhaul is expensive and multicast is not useful there.
        # Keep multicast/mDNS usable on WiFi/loopback, but never emit IPv4/IPv6
        # multicast on cellular point-to-point interfaces.
        oifname "wwan*" ip daddr 224.0.0.0/4 counter drop
        oifname "ppp*" ip daddr 224.0.0.0/4 counter drop
        oifname "wwan*" ip6 daddr ff00::/8 counter drop
        oifname "ppp*" ip6 daddr ff00::/8 counter drop
    }
}
NFT
EOF
    chmod 0755 /usr/local/sbin/pirate-backhaul-firewall

    cat > /etc/systemd/system/pirate-multicast-policy.service <<'EOF'
[Unit]
Description=Pirate multicast route policy
After=network-pre.target NetworkManager.service
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/pirate-multicast-policy
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/pirate-backhaul-firewall.service <<'EOF'
[Unit]
Description=Pirate cellular backhaul firewall
After=network-pre.target
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/pirate-backhaul-firewall
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now pirate-multicast-policy.service
    if command -v nft >/dev/null 2>&1; then
        systemctl enable --now pirate-backhaul-firewall.service
    else
        warn "nft not installed yet; cellular multicast firewall will be enabled after package install"
    fi
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
[[ $EUID -eq 0 ]] || exec sudo --preserve-env=FORCE,SKIP_WISDOM,STATION_LAT,STATION_LON,UPLOADER_CALLSIGN,SONDEHUB_CONTACT_EMAIL,SONDEHUB_UPLOAD_RATE,LTE_APN,LTE_USERNAME,LTE_PASSWORD,LTE_PIN,LTE_CONNECTION_NAME -- "$0" "$@"
# the unprivileged user auto_rx will run as (the invoker of sudo, else 'pi')
RUN_USER="${SUDO_USER:-pi}"
id "$RUN_USER" >/dev/null 2>&1 || die "run user '$RUN_USER' does not exist"

MDNS_STATUS="${STATION}.local"
MDNS_DATA="${STATION}-pcm.local"
# Limit build parallelism on low-RAM boards: 4 parallel gcc can OOM a 512MB Pi Zero.
JOBS=$(nproc); [[ $(free -m | awk '/^Mem:/{print $2}') -lt 1024 ]] && JOBS=2
export DEBIAN_FRONTEND=noninteractive
log "Setting up sonde receiver '$STATION' (radiod@$STATION, mDNS $MDNS_STATUS/$MDNS_DATA), auto_rx as user '$RUN_USER'"
configure_backhaul_cost_controls

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
if ! done_already 2-cellular; then
    log "[2c/5] cellular backhaul tools"
    apt-get update -qq
    apt-get install -y --no-install-recommends modemmanager libqmi-utils nftables
    mark_done 2-cellular
fi
if ! command -v nft >/dev/null 2>&1; then
    log "Reconciling nftables package"
    apt-get update -qq
    apt-get install -y --no-install-recommends nftables
fi
log "Reconciling cellular backhaul support"
configure_lte_backhaul
configure_avahi_backhaul_policy
configure_mdns_resolver_policy
configure_multicast_backhaul_policy
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
