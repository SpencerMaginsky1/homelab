#!/usr/bin/env bash
# Install/update the daily health check. Run: sudo bash install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
install -o root -g root -m 755 homelab-healthcheck homelab-watchdog /usr/local/bin/
[[ -e /etc/homelab-healthcheck.conf ]] || install -o root -g root -m 600 homelab-healthcheck.conf /etc/homelab-healthcheck.conf
install -o root -g root -m 644 homelab-healthcheck.service homelab-healthcheck.timer homelab-watchdog.service homelab-watchdog.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now homelab-healthcheck.timer homelab-watchdog.timer
echo "== next runs:"; systemctl list-timers homelab-healthcheck.timer homelab-watchdog.timer --no-pager || true
echo "== watchdog dry run (changes nothing):"; /usr/local/bin/homelab-watchdog --dry-run || true
echo "== done. To send a test report now: sudo systemctl start homelab-healthcheck"
