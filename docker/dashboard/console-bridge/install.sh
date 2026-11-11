#!/usr/bin/env bash
# Installs the dashboard's two host bridges as systemd user services (no sudo). README 3.14.
#   mc-console-bridge  types commands into the Minecraft console
#   term-bridge        the Terminal page's shell (tmux session "dashboard")
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HOME/.config/systemd/user" "$here/../run"
for svc in mc-console-bridge term-bridge; do
  cp "$here/$svc.service" "$HOME/.config/systemd/user/"
done
systemctl --user daemon-reload
for svc in mc-console-bridge term-bridge; do
  systemctl --user enable --now "$svc.service"
  systemctl --user restart "$svc.service"
  systemctl --user --no-pager status "$svc.service" | head -5
done
