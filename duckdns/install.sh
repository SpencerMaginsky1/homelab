#!/usr/bin/env bash
# Install the DuckDNS updater. Run: sudo bash install.sh
# Prompts for the token (input hidden) and stores it only in /etc/duckdns.conf (root-only).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
DOMAIN=example
if [[ ! -s /etc/duckdns.conf ]]; then
  read -rsp "Paste your DuckDNS token (hidden): " TOKEN; echo
  [[ $TOKEN =~ ^[0-9a-fA-F-]{36}$ ]] || { echo "That doesn't look like a DuckDNS token (36-char UUID)."; exit 1; }
  umask 077
  printf 'DUCKDNS_DOMAIN=%s\nDUCKDNS_TOKEN=%s\nLAN_IF=enp2s0\n' "$DOMAIN" "$TOKEN" > /etc/duckdns.conf
  chmod 600 /etc/duckdns.conf
fi
install -o root -g root -m 755 duckdns-update /usr/local/bin/duckdns-update
install -o root -g root -m 644 duckdns-update.service duckdns-update.timer /etc/systemd/system/
systemctl daemon-reload
echo "== first update:"
if /usr/local/bin/duckdns-update; then
  journalctl -t duckdns -n 1 --no-pager -o cat || true
  echo "OK (no output above = record already correct)"
else
  echo "Update failed:"; journalctl -t duckdns -n 3 --no-pager -o cat; exit 1
fi
systemctl enable --now duckdns-update.timer
systemctl list-timers duckdns-update.timer --no-pager || true
echo "== DNS check (may take a minute to propagate):"
getent hosts "$DOMAIN.duckdns.org" || echo "not resolving yet"
