#!/usr/bin/env bash
# Install/update the GolfApp web server (port 8001, reachable from the LAN and tailnet
# only) and the updater that pulls it from GitHub at 04:00. Run: sudo bash install.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
[[ -d /home/spencer/Desktop/GolfApp/.git ]] \
  || runuser -u spencer -- git clone -q https://github.com/a-friend/GolfApp.git /home/spencer/Desktop/GolfApp
# Stop a hand-started copy (tmux session "golf") so the service can take port 8001
runuser -u spencer -- tmux kill-session -t golf 2>/dev/null || true
pkill -u spencer -f "^python3 -m http.server 8001" || true
install -o root -g root -m 755 golf-serve /usr/local/bin/golf-serve
install -o root -g root -m 644 homelab-golf.service /etc/systemd/system/
# Firewall: LAN + tailnet only (same as Uptime Kuma/Beszel). The router doesn't forward it, so not the internet.
ufw allow from 192.168.1.0/24 to any port 8001 proto tcp comment 'golfapp LAN'
ufw allow in on tailscale0 to any port 8001 proto tcp comment 'golfapp tailnet'
ufw allow in on br-homarr to any port 8001 proto tcp comment 'homarr -> golfapp'   # Homarr tile status check
systemctl daemon-reload
systemctl enable homelab-golf.service
systemctl restart homelab-golf.service
bash ../updater/install.sh >/dev/null                # 04:00 GitHub pull (also refreshes the health check)
sleep 1
systemctl --no-pager status homelab-golf.service | head -5
echo "== listening: $(ss -ltn | grep -o '0.0.0.0:8001' || echo 'NOT on 0.0.0.0:8001')"
echo "== test LAN address: $(curl -s -o /dev/null -w '%{http_code}' http://192.168.1.179:8001/) (200 = working)"
echo "== test .git hidden: $(curl -s -o /dev/null -w '%{http_code}' http://192.168.1.179:8001/.git/config) (404 = hidden)"
echo "== firewall:"; ufw status | grep 8001
echo "== open from the LAN: http://192.168.1.179:8001  ·  tailnet: http://spencer-server:8001"
