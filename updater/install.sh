#!/usr/bin/env bash
# Install/update homelab-updater (+ homelab-rollback) and refresh the health check / watchdog.
# Run: sudo bash install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
install -o root -g root -m 755 homelab-updater /usr/local/bin/homelab-updater
ln -sf /usr/local/bin/homelab-updater /usr/local/bin/homelab-rollback
install -o root -g root -m 644 homelab-updater.service homelab-updater.timer /etc/systemd/system/
install -d -o root -g root -m 700 /var/backups/homelab /var/lib/homelab-updater
systemctl daemon-reload
systemctl enable --now homelab-updater.timer
bash ../healthcheck/install.sh >/dev/null            # watchdog pause-during-updates + report changes
echo "== timers:"; systemctl list-timers 'homelab-*' --no-pager || true
echo "== current status:"; /usr/local/bin/homelab-updater status
echo "== done. Preview what's out of date (changes nothing): sudo homelab-updater check"
