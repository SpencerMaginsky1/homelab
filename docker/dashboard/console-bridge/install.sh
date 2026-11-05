#!/usr/bin/env bash
# Installs the Minecraft console bridge as a systemd user service (no sudo). README 3.14.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HOME/.config/systemd/user" "$here/../run"
cp "$here/mc-console-bridge.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now mc-console-bridge.service
systemctl --user restart mc-console-bridge.service
systemctl --user --no-pager status mc-console-bridge.service | head -5
