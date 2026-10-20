#!/usr/bin/env bash
# Install/update the docs web server (port 8000, localhost only). Run: sudo bash install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
# Stop a hand-started nohup copy so the service can take port 8000
pkill -u spencer -f "^python3 -m http.server 8000" || true
sleep 1
install -o root -g root -m 644 homelab-docs.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now homelab-docs.service
sleep 1
systemctl --no-pager status homelab-docs.service | head -5
echo "== test: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/network-diagram.svg) (200 = working)"
