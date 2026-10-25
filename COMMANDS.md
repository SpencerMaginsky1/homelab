# Homelab Commands — Spencer-Server

Quick reference for every command used to run and fix this server. *(Section numbers §3–§9 are referenced by the Automation panel in `network-diagram.svg`, so keep them stable or update the diagram too.)* **How it works and why** is in [README.md](SERVER.md); this file is just **what to type**.

- Commands marked **`sudo`** need your password.
- `<svc>` is one of `homarr`, `uptime-kuma`, `beszel`, `dawarich`, `minecraft` or `plex`. `golfapp` works with `apply` only (it pulls from GitHub).
- All times are New York time.

---

## Contents
1. [Is everything OK?](#1-is-everything-ok) · 2. [Planned maintenance](#2-planned-maintenance) · 3. [Daily health check](#3-daily-health-check) · 4. [Watchdog](#4-watchdog) · 5. [Updates & rollback](#5-updates--rollback) · 6. [Minecraft backups](#6-minecraft-backups) · 7. [Minecraft server](#7-minecraft-server) · 8. [DuckDNS](#8-duckdns) · 9. [Network, exit node & firewall](#9-network-exit-node--firewall) · 10. [Docker services](#10-docker-services) · 11. [Plex](#11-plex) · 12. [Notifications (ntfy)](#12-notifications-ntfy) · 13. [Docs & GolfApp web servers](#13-docs--golfapp-web-servers) · 14. [Reinstalling the homelab tools](#14-reinstalling-the-homelab-tools)

---

## 1. Is everything OK?
Run after a reboot, or whenever something seems off.
```bash
sudo homelab-healthcheck --dry-run                 # full check (~35 items), prints the report, sends nothing
systemctl list-timers 'homelab-*' mc-backup.timer duckdns-update.timer   # all 5 timers scheduled
docker ps --format '{{.Names}}\t{{.Status}}'       # 8 containers up / healthy
tmux ls                                            # "minecraft" session exists
curl -4 -s ifconfig.me; echo                       # 198.51.100.20 = traffic via the Pi exit node
sudo homelab-updater status                        # versions, holds, update backups
sudo mc-backup list                                # newest Minecraft restore point ~03:30 today
systemctl --failed                                 # should list nothing
ls ~/.homelab-maintenance 2>/dev/null              # should print nothing (else the watchdog is paused)
systemctl is-active homelab-docs homelab-golf      # docs :8000 + GolfApp :8001 web servers
```

## 2. Planned maintenance
Pause the watchdog before you stop Minecraft, Plex or a container **on purpose**, otherwise it restarts them within about 15 min.
```bash
touch ~/.homelab-maintenance        # pause watchdog repairs (auto-expires after 24 h)
rm ~/.homelab-maintenance           # resume
```

## 3. Daily health check
Runs at **08:00**, see README 3.6.
```bash
sudo systemctl start homelab-healthcheck            # run it now (sends the ntfy push)
sudo homelab-healthcheck --dry-run                  # preview the report, send nothing (still asks Claude for a summary if there are problems)
systemctl list-timers homelab-healthcheck.timer     # next run
journalctl -u homelab-healthcheck -n 50             # last run's output
sudo nano /etc/homelab-healthcheck.conf             # settings: ntfy topic, expected IPs, disk
```

## 4. Watchdog
Runs **every 15 min**, see README 3.7.
```bash
sudo homelab-watchdog --dry-run                     # what it would fix right now (changes nothing)
journalctl -t homelab-watchdog --since -24h         # what it restarted (FIX / FIXED / FAILED / RECOVERED)
sudo ls /var/lib/homelab-watchdog/                  # strike counters, restart attempts, alerted flags
```

## 5. Updates & rollback
Runs daily at **04:00**, see README 3.10.
```bash
sudo homelab-updater status                         # versions, holds, available backups
sudo homelab-updater check                          # what's out of date (pulls images; nothing running changes)
sudo homelab-updater apply <svc>                    # update now: backup → update → health check → auto-rollback if bad
sudo homelab-updater apply <svc> --force            # same, even if already current (good for testing)
sudo homelab-updater apply minecraft                # needs 0 players online (add --force to override)

sudo homelab-rollback <svc>                         # undo the last update: previous version + its data, then HOLD
sudo homelab-rollback <svc> <YYYYmmdd-HHMMSS>       # roll back to a specific backup (see status)
sudo homelab-updater unhold <svc>                   # allow updates again after a rollback

journalctl -t homelab-updater                       # full log
sudo cat /var/lib/homelab-updater/history.log       # what the 8 AM report reads (timestamp|message)
sudo ls /var/backups/homelab/<svc>/                 # pre-update backups (last 3; Minecraft last 2)
```
- **Auto:** Homarr, Uptime Kuma, Beszel.
- **Ask first (📦 push):** Minecraft, Dawarich.
- **Plex:** snap updates itself. `sudo homelab-rollback plex` = `snap revert` + hold.
- **GolfApp:** fast-forward `git pull` of `main` from GitHub (skipped if the clone is on another branch or has edits). `sudo homelab-updater apply golfapp` pulls now. No rollback: GitHub is the source of truth.

## 6. Minecraft backups
Runs nightly at **03:30**, see README 3.11.
```bash
sudo mc-backup list                                 # restore points (7 daily / 4 weekly / 6 monthly)
sudo mc-backup                                      # back up now (online players get 5-min warning + 10 s countdown)
sudo mc-backup now                                  # back up now, no warnings
sudo mc-backup restore latest                       # restore newest (asks you to type "restore")
sudo mc-backup restore <ID>                         # restore a specific point (ID from "list")
sudo mc-backup restore <ID> --yes                   # ...without the confirmation prompt
sudo mc-backup check                                # integrity check (also automatic on Sundays)
sudo mc-backup stats                                # repository size
journalctl -t mc-backup -n 30                       # recent runs
sudo cat /etc/mc-backup.pass                        # 🔑 backup password (copy is in your password manager)
```
- **After a restore,** the old world is kept as `~/Desktop/MineCraft Server/world.before-restore-<time>`. Delete it once you're happy:
  ```bash
  rm -rf "/home/spencer/Desktop/MineCraft Server/world.before-restore-<time>"
  ```

## 7. Minecraft server
Vanilla, in tmux session `minecraft`, see README 3.5.
```bash
tmux attach -t minecraft                            # open the console (detach: Ctrl-b then d; never Ctrl-C)
tmux send-keys -t minecraft "list" Enter            # who's online (answer appears in the log/console)
tail -f "/home/spencer/Desktop/MineCraft Server/logs/latest.log"   # live log
```
**In the console** (after `tmux attach -t minecraft`):
```text
list                       # players online
whitelist add <name>       # let a friend join (whitelist is ON - keep it on)
whitelist remove <name>
say <message>              # message everyone
stop                       # save + shut down cleanly
```
**Restart the server safely** (when nobody's online):
```bash
touch ~/.homelab-maintenance                        # stop the watchdog interfering
tmux send-keys -t minecraft "stop" Enter            # wait until the console shows a shell prompt again
tmux send-keys -t minecraft "cd '/home/spencer/Desktop/MineCraft Server' && ./start.sh" Enter
rm ~/.homelab-maintenance
```
**Change the RAM:** edit `-Xms6G -Xmx6G` in `~/Desktop/MineCraft Server/start.sh`, then restart as above. The 8 GB original is saved as `start.sh.bak-8G`.

## 8. DuckDNS
`example.duckdns.org`, updated every 5 min, see README 3.8.
```bash
getent hosts example.duckdns.org                   # what the name points to...
curl -4 -s --interface 192.168.1.179 ifconfig.me; echo   # ...must equal the home IP
sudo duckdns-update                                 # push the home IP now
journalctl -t duckdns -n 10                         # only "updated" / "FAILED" lines (quiet otherwise)
curl -s https://api.mcsrvstat.us/3/example.duckdns.org | jq '{online, version, players: .players.online}'   # what friends/Homarr see
```

## 9. Network, exit node & firewall
See README section 4.
```bash
tailscale status                                    # tailnet devices; raspberrypi = "active; exit node"
curl -4 -s ifconfig.me; echo                        # 198.51.100.20 = via Pi · 203.0.113.10 = NOT via Pi
sudo tailscale set --exit-node=                     # exit node OFF (temporarily)
sudo tailscale set --exit-node=raspberrypi --exit-node-allow-lan-access=true   # exit node ON (LAN access required!)

ip rule | grep -E '520[89]'                         # policy rules 5208 + 5209 present
ip route show table 128                             # home-WAN table
sudo /etc/NetworkManager/dispatcher.d/50-policy-routing enp2s0 up   # re-apply the routing rules
journalctl -t policy-routing -b                     # "applied: ..." since boot
sysctl net.ipv4.ip_forward net.ipv4.conf.enp2s0.send_redirects     # 1 and 0 (gateway mode)

sudo ufw status verbose                             # firewall rules
sudo iptables -t nat -S POSTROUTING | grep tailscale0               # gateway NAT rule
journalctl -k | grep 'UFW BLOCK' | tail             # what the firewall dropped
```

## 10. Docker services
Stacks live in `~/Desktop/docker/`.

| Service | Folder | Web UI |
|---|---|---|
| Homarr | `~/Desktop/docker/homarr` | http://192.168.1.179:7575 |
| Uptime Kuma | `~/Desktop/docker/uptime-kuma` | http://192.168.1.179:3001 |
| Beszel | `~/Desktop/docker/beszel` | http://192.168.1.179:8090 |
| Dawarich | `~/Desktop/docker` (project `docker`) | http://192.168.1.179:3000 |
| Ship Tracker | `~/Desktop/docker/ships` | http://192.168.1.179:8100 |

```bash
cd ~/Desktop/docker/<folder>
docker compose ps                                   # status
docker compose logs --tail 50 -f                    # logs
docker compose restart                              # restart (pause the watchdog first if it's planned)
docker compose stop                                 # stop
docker compose up -d                                # start
docker stats --no-stream                            # CPU / RAM per container
```
**To update,** use `sudo homelab-updater apply <svc>` (section 5), **not** `docker compose pull && up -d`. The bare docker commands skip the backup and rollback.

**Ship Tracker** (README 3.13) is built locally and the updater doesn't manage it. Refresh it with `cd ~/Desktop/docker/ships && docker compose build --pull && docker compose up -d`. Check the feed with `curl -s localhost:8100/health` and `docker logs ships`. The API key and map area are in `.env`; run `docker compose up -d` after editing it.

## 11. Plex
```bash
snap list plexmediaserver                           # version / revision
sudo snap restart plexmediaserver                   # restart
sudo homelab-rollback plex                          # revert the last snap update + hold it
sudo homelab-updater unhold plex                    # allow snap updates again
curl -s http://127.0.0.1:32400/identity             # is it answering?
```

## 12. Notifications (ntfy)
```bash
sudo grep NTFY_URL /etc/homelab-healthcheck.conf    # your private topic (treat like a password)
curl -d "test" ntfy.sh/<topic>                      # send a test push to your phone
curl -s "ntfy.sh/<topic>/json?poll=1&since=12h" | jq -r '.title'   # what's on the topic (last ~12 h)
```
- **Uptime Kuma test:** Settings → Notifications → Phone (ntfy) → **Test**.

## 13. Docs & GolfApp web servers
See README 7 (docs) and 3.12 (GolfApp).
```bash
systemctl status homelab-docs                       # web server (localhost:8000, starts at boot)
sudo systemctl restart homelab-docs                 # restart it
sudo systemctl disable --now homelab-docs           # stop it and keep it off after reboots
ssh -L 8000:127.0.0.1:8000 spencer@192.168.1.179    # on your PC, then open http://localhost:8000/network-diagram.svg
systemctl status homelab-golf                       # GolfApp web server (port 8001, starts at boot)
# GolfApp: open http://192.168.1.179:8001 (LAN) or http://spencer-server:8001 (tailnet) - no tunnel needed
sudo homelab-updater apply golfapp                  # pull GolfApp from GitHub now (also runs daily at 04:00)
sudo tailscale serve --bg 8000                      # phone: https://spencer-server.tailnet-name.ts.net/network-diagram.svg
sudo tailscale serve --https=443 off                # stop sharing to the tailnet
```

## 14. Reinstalling the homelab tools
Run after editing the sources in `~/Desktop/Claud`. Every installer is safe to re-run, and none of them overwrite existing settings in `/etc`.
```bash
sudo bash ~/Desktop/Claud/healthcheck/install.sh    # health check + watchdog
sudo bash ~/Desktop/Claud/updater/install.sh        # updater + rollback (also re-runs the health check installer)
sudo bash ~/Desktop/Claud/duckdns/install.sh        # DuckDNS (asks for the token only if /etc/duckdns.conf is missing)
sudo bash ~/Desktop/Claud/docs-server/install.sh    # docs web server (port 8000, localhost only)
sudo bash ~/Desktop/Claud/golf-server/install.sh    # GolfApp web server (port 8001) + updater with the 04:00 GitHub pull
sudo install -o root -g root -m 755 ~/Desktop/Claud/mc-backup/mc-backup /usr/local/bin/mc-backup   # mc-backup script only
sudo bash ~/Desktop/Claud/mc-backup/install.sh      # full mc-backup setup (takes a backup immediately)
```
