#!/usr/bin/env bash
#
# Provision Pirate's WireGuard client from a one-shot helper on the VPN server.
#
# Required server-side helper:
#   ssh "$VPN_SERVER_HOST" get-vpn-key.py --name "$VPN_PEER_NAME" ...

set -euo pipefail

PI_HOST="${PI_HOST:-pirate.local}"
VPN_SERVER_HOST="${VPN_SERVER_HOST:-vpn.circlemud.org}"
VPN_PEER_NAME="${VPN_PEER_NAME:-pirate}"
CLIENT_INTERFACE="${CLIENT_INTERFACE:-wg0}"
FORCE_WIREGUARD="${FORCE_WIREGUARD:-0}"
REUSE_WIREGUARD="${REUSE_WIREGUARD:-$FORCE_WIREGUARD}"

log() { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[FATAL]\033[0m %s\n' "$*" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || die "python3 is required"

if ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI_HOST" "sudo test -s /etc/wireguard/${CLIENT_INTERFACE}.conf" 2>/dev/null; then
    if [[ "$REUSE_WIREGUARD" != 1 ]]; then
        log "$PI_HOST already has /etc/wireguard/${CLIENT_INTERFACE}.conf (REUSE_WIREGUARD=1 to rotate in place)"
        exit 0
    fi
fi

reuse_arg=()
[[ "$REUSE_WIREGUARD" == 1 ]] && reuse_arg+=(--reuse)

log "Requesting WireGuard peer '$VPN_PEER_NAME' from $VPN_SERVER_HOST"
peer_json="$(
    ssh -o BatchMode=yes -o ConnectTimeout=8 "$VPN_SERVER_HOST" \
        get-vpn-key.py \
        --name "$VPN_PEER_NAME" \
        "${reuse_arg[@]}"
)"

tmp_conf="$(mktemp)"
trap 'rm -f "$tmp_conf"' EXIT

PEER_JSON="$peer_json" python3 - "$tmp_conf" <<'PY'
import json
import os
import sys

peer = json.loads(os.environ["PEER_JSON"])
path = sys.argv[1]
addresses = ", ".join(peer["addresses"])
allowed_ips = ", ".join(peer["allowed_ips"])
keepalive = peer.get("persistent_keepalive", 25)

content = f"""# Managed by sonde-search/pirate/setup-wireguard.sh.
[Interface]
Address = {addresses}
PrivateKey = {peer["private_key"]}

[Peer]
PublicKey = {peer["server_public_key"]}
Endpoint = {peer["endpoint"]}
AllowedIPs = {allowed_ips}
PersistentKeepalive = {keepalive}
"""

with open(path, "w", encoding="utf-8") as f:
    f.write(content)
PY

log "Installing wireguard-tools on $PI_HOST"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI_HOST" \
    "sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends wireguard-tools"

log "Installing client config on $PI_HOST"
remote_tmp="/tmp/${CLIENT_INTERFACE}.conf.$$"
scp -q "$tmp_conf" "$PI_HOST:$remote_tmp"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI_HOST" \
    "sudo install -d -m 700 /etc/wireguard && sudo install -o root -g root -m 600 '$remote_tmp' '/etc/wireguard/${CLIENT_INTERFACE}.conf' && rm -f '$remote_tmp' && sudo systemctl enable --now 'wg-quick@${CLIENT_INTERFACE}'"

log "WireGuard status on $PI_HOST"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$PI_HOST" \
    "ip -br addr show '${CLIENT_INTERFACE}'; sudo wg show '${CLIENT_INTERFACE}'"
