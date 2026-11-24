#!/usr/bin/env bash
# Turn CPU turbo off now and at every boot. Undo: sudo systemctl disable --now cpu-no-turbo
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
install -m 644 "$(dirname "$0")/cpu-no-turbo.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cpu-no-turbo.service
echo "turbo off: $(cat /sys/devices/system/cpu/intel_pstate/no_turbo) (1 = off)"
