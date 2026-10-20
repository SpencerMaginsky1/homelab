# Home Network & Services — Spencer-Server

Notes for future me: what's on the tailnet, what runs on this server, how traffic flows, and how to fix or rebuild things.

**➡ For just the commands, see [COMMANDS.md](COMMANDS.md)**, a cheat sheet grouped by task.

_Last verified: 2026-10-19 17:00: Ship Tracker added and checked (3.13): container healthy, live NYC feed, map loads with no page errors, Kuma "Ship Tracker" up and on the `home` page (7 monitors, all up). Dawarich is on 1.16.0 with 6,329 points, and its Kuma monitor uses `/api/v1/health`. user@1000 lingering is on (see 6), so it no longer fails on logout. Previously, 2026-10-17 04:55: no failed units, 8/8 containers up, all web UIs answering (Homarr, Kuma, Beszel, Dawarich, Plex, docs :8000, GolfApp :8001), all 5 timers scheduled, and the 03:30 backup and 04:00 updater ran cleanly. Installed scripts and units all match the sources here, including the health check with its new GolfApp check (installed 04:49). Uptime Kuma has 6 monitors, all on the `home` status page and all up (GolfApp and Homarr added to the page that morning, 3.2). The GolfApp service, firewall rules and Homarr tile were added and checked that night (3.12). Still on Ubuntu 25.04 (end of life, see to-dos). Previously, 2026-10-16 16:05, after installing 151 package updates (incl. systemd) and rebooting: kernel 6.14.0-37, no reboot pending, dpkg clean, no failed units. 8/8 containers up (healthchecks healthy), all 5 web UIs answering, Minecraft 26.3 back up via `@reboot`, Plex 1.43.4 active. Exit node active (public IP = Pi), DuckDNS = home IP, rules 5208/5209 re-applied by the dispatcher, forwarding on and redirects off. All 5 timers scheduled (watchdog and DuckDNS already ran cleanly since boot), installed scripts and units match the sources here. Earlier the same day the 03:30 backup, 04:00 updater and 08:00 report (0 failures) all ran on schedule. On 2026-10-15 it rebooted and came back up on its own, and that evening gained the health check, watchdog, DuckDNS, the 6 GB Minecraft heap, the Samsung TV, the Homarr widgets and v2.6.0 update, the auto-updater with rollback, and nightly Minecraft backups with player warnings._

![Network diagram](network-diagram.svg)

**What's in `~/Desktop/Claud`:**
| Path | What |
|---|---|
| `COMMANDS.md` | Command cheat sheet: every homelab command grouped by task (health, maintenance, updates/rollback, backups/restore, Minecraft, DuckDNS, network, Docker, Plex, ntfy, the docs and GolfApp web servers). Its section numbers (§3–§9) are referenced by the diagram's Automation panel, so **if you renumber sections, update the diagram too**. |
| `README.md` | This file. The daily health check also feeds it to Claude as context, so keep it accurate. |
| `network-diagram.svg` | The network diagram: dark mode, and it scales to the browser window. Shows the internet side (Minecraft players, DuckDNS, ntfy), the apartment LAN, the server's services (including Docs :8000 and GolfApp :8001), the tailnet, numbered paths ①–⑩ with a legend, and an **Automation panel** at the bottom with every timed job (recurring, the nightly 03:30 → 04:00 → 08:00 sequence, and at boot; each card points to its `COMMANDS.md` section, e.g. "→ COMMANDS.md §6"), the **ntfy flow** (⑥): health report, watchdog, updater, backups and Uptime Kuma → ntfy.sh → iPhone app and Homarr widget, and a **Documentation** box (plus a matching "Docs" legend entry) pointing to `COMMANDS.md`, `README.md` and the tool folders. Open it in any browser (see 7 → *Viewing the network diagram*, or COMMANDS.md §13). |
| `healthcheck/` | Sources plus `install.sh` for the daily health check (3.6) and watchdog (3.7). The `.conf` here is a template; the real one is `/etc/homelab-healthcheck.conf`. |
| `duckdns/` | Sources plus `install.sh` for the DuckDNS updater (3.8). |
| `updater/` | Sources plus `install.sh` for the auto-updater and rollback tool (3.10). |
| `mc-backup/` | Sources plus `install.sh` for the nightly Minecraft world backups (3.11). |
| `UPGRADE-26.04.md` | Step-by-step plan for the Ubuntu 25.04 → 26.04.1 LTS upgrade (25.04 is end of life). Delete or archive it once the upgrade is done. |
| `golf-server/` | `golf-serve` (a web server that hides `.git`), unit and `install.sh` for `homelab-golf.service`, which serves a friend's golf app from `~/Desktop/GolfApp` on port 8001 to the LAN and tailnet (3.12). |
| `github/` | `sync-repos.sh` copies this folder, the Docker Compose files and the Minecraft start scripts to two GitHub repos: **`SpencerMaginsky1/homelab-private`** (private; the real files) and **`SpencerMaginsky1/homelab`** (public, linked on the resume; IPs, domains and names swapped for placeholders, with `PUBLIC-README.md` as its front page). It never copies `.env` files or data, blanks the Dawarich signing key, and refuses to commit if a secret or personal detail slips through. The ship tracker goes only to the private repo. After editing docs or scripts, run `~/Desktop/Claud/github/sync-repos.sh` to preview the changes, then `… --push "message"`. The working copies are in `~/repos/`. |
| `docs-server/` | Unit plus `install.sh` for `homelab-docs.service`, the localhost-only web server for this folder (7 → *Viewing the network diagram*). |

---

## 1. Tailscale network (tailnet `tailnet-name.ts.net`)

| Device | Tailscale IP | OS | Role |
|---|---|---|---|
| **spencer-server** (this machine) | `100.64.0.10` | Ubuntu 25.04 (end of life; upgrade planned) | Main server: Minecraft, Plex, Docker services, GolfApp, LAN gateway. **Uses the Pi as its exit node.** |
| **raspberrypi** | `100.64.0.20` | Linux (Raspberry Pi OS) | **Exit node.** All of this server's internet traffic leaves from its location. WAN IP `198.51.100.20`. Runs a Beszel agent. |
| **spencer** | `100.64.0.30` | Windows | Desktop PC |
| **iphone-15-pro** | `100.64.0.40` | iOS | Phone. Use it to reach the dashboards when away from home. |
| **friend-pc** | `100.64.0.50` | Linux | A node **shared from another account** (`a-friend@`, tailnet `other-tailnet`). Not mine to manage. |

MagicDNS works: `spencer-server`, `raspberrypi` and so on resolve on any tailnet device.

### Public IPs, used to tell which path traffic took
- `198.51.100.20`: the **Pi's** WAN. This is what this server should show (`curl -4 ifconfig.me`).
- `203.0.113.10`: the **home** WAN. If the server shows this, the exit node isn't being used.
- `example.duckdns.org` → **home** WAN (currently `203.0.113.10`), kept current by `duckdns-update` (see 3.8). Check with `getent hosts example.duckdns.org`.

---

## 2. Spencer-Server at a glance

| | |
|---|---|
| Hostname | `Spencer-Server` |
| LAN IP | `192.168.1.179/24` on `enp2s0`, from DHCP. **Reserve this IP on the router.** Lots of things depend on it. |
| Router / LAN gateway | `192.168.1.1` |
| Samsung TV | `192.168.1.153`, Samsung CU7000 65" (Tizen). Plex client: streams straight from `192.168.1.179:32400` over the LAN, allowed by the ufw "plex LAN" rule. Uses the router as its gateway, so it isn't tunneled. Plex also discovers it as a DLNA renderer via SSDP. |
| CPU / RAM / Disk | Intel i7-4790K, 15 GiB RAM, `/dev/sda2` 457 GB |
| User | `spencer` (in the `sudo` and `docker` groups) |
| Firewall | **ufw**, enabled, default deny |

---

## 3. Services

| Service | URL | Runs as | Location | Auto-start |
|---|---|---|---|---|
| **Homarr** (main dashboard) | http://192.168.1.179:7575 | Docker | `~/Desktop/docker/homarr/` | `restart: unless-stopped` |
| **Uptime Kuma** (up/down monitoring) | http://192.168.1.179:3001 | Docker, host network | `~/Desktop/docker/uptime-kuma/` | `restart: unless-stopped` |
| **Beszel** (CPU/RAM/temp/disk/network graphs) | http://192.168.1.179:8090 | Docker hub + agent, host network | `~/Desktop/docker/beszel/` | `restart: unless-stopped` |
| **Dawarich** (location history) | http://192.168.1.179:3000 | Docker (4 containers) | `~/Desktop/docker/docker-compose.yml` | `always` / `unless-stopped` |
| **Minecraft server** | `192.168.1.179:25565` (LAN) · **`example.duckdns.org`** (internet) | Native Java in tmux session `minecraft` | `~/Desktop/MineCraft Server/` | crontab `@reboot` |
| **GolfApp** (friend's golf web app, `a-friend/GolfApp`) | http://192.168.1.179:8001 (3.12) | systemd `homelab-golf.service` (Python `golf-serve`) | `~/Desktop/GolfApp/` (git clone) | systemd |
| **Ship Tracker** (live AIS map of ships around NYC and Long Island) | http://192.168.1.179:8100 (3.13) | Docker (`ships`, built locally) | `~/Desktop/docker/ships/` | `restart: unless-stopped` |
| **Docs** (this folder: README, COMMANDS, diagram) | http://localhost:8000 via SSH tunnel (7) | systemd `homelab-docs.service` (Python, localhost only) | `~/Desktop/Claud/` | systemd |
| **Plex** | http://192.168.1.179:32400/web | snap `plexmediaserver` | `~/Desktop/Plex_Server/` | snap service |
| SSH | port 22 | system | | system |
| Samba | ports 139/445 | system | | system |

Over Tailscale, replace `192.168.1.179` with `spencer-server` or `100.64.0.10`.
Dawarich only accepts the hostnames listed in its `APPLICATION_HOSTS` setting: `localhost, 127.0.0.1, 192.168.1.179, 100.64.0.10`.

### Automation at a glance
| When | What | Section |
|---|---|---|
| Every 5 min | `duckdns-update`: keeps `example.duckdns.org` on the home IP | 3.8 |
| Every 15 min | `homelab-watchdog`: restarts what doesn't restart itself | 3.7 |
| **03:30** | `mc-backup`: live Minecraft world backup (5-min player warning if anyone is online) | 3.11 |
| **04:00** | `homelab-updater`: auto-updates Homarr, Kuma and Beszel; 📦 asks about Minecraft and Dawarich; pulls GolfApp from GitHub | 3.10, 3.12 |
| **08:00** | `homelab-healthcheck`: daily ✅/⚠️/🚨 report to ntfy (Claude summary on problems) | 3.6 |
| Continuous | Uptime Kuma checks every 60 s and pushes down/up alerts | 3.2 |

All times are New York time. Every push goes to the same private ntfy topic, which is also shown on the Homarr Notifications widget.

### 3.1 Homarr (dashboard)
- The one page that shows everything. **Board contents** (as of 2026-10-17):

| Widget | Integration | Notes |
|---|---|---|
| **Uptime Kuma** | Uptime Kuma, `http://192.168.1.179:3001` | Reads the Kuma status page with slug `home` |
| **Beszel Systems (Grid)** | Beszel, `http://192.168.1.179:8090` | spencer-server and raspberrypi side by side. The login is the Beszel **email** plus password |
| **Notifications** | ntfy, `https://ntfy.sh` | History of the private topic: daily health reports, watchdog 🔧/🚨 pushes, Uptime Kuma down/up. The topic is stored encrypted in Homarr; **no API key** is needed. ntfy.sh only keeps about **12 h**, so the widget shows roughly the last half-day (the phone keeps everything) |
| **Minecraft Server Status** | none | Address `example.duckdns.org` (Java). Queried through the public `api.mcsrvstat.us`, so it only works because the server is internet-reachable, and it lags about 5 min (cache) |
| **Weather**, **Date and time** | none | |
| App tiles | none | Including **Dawarich** and **GolfApp** (`http://192.168.1.179:8001`), both with a status check. Homarr also auto-created an "ntfy" app when the integration was added |

- Runs on its **own Docker bridge, `br-homarr` (172.19.0.0/16)**, with only port 7575 published. **Don't switch it to host networking.** It runs internal services on 3000, 3001 and 6379 that clash with dawarich and Uptime Kuma, and the container then crash-loops.
- Integration URLs inside Homarr must use **`http://192.168.1.179:<port>`**. `localhost` from inside its container means the container itself.
- **Beszel login in Homarr uses the email address**, not a username (Beszel only accepts email). A 400 "auth-with-password" error means the login details are wrong.
- **Version:** **v2.6.0** (updated 2026-10-15 from v2.5.2; no schema changes, board and integrations carried over). **Updates are now automatic** via `homelab-updater` (3.10), and `sudo homelab-rollback homarr` undoes one. The manual method used for v2.6.0 is kept below for reference. **Before a manual update, check the release notes** (https://github.com/homarr-labs/homarr/releases) for breaking changes. Then:
  1. Back up: `docker compose stop`, then copy `appdata/` (`backups/appdata-<version>-<date>.tgz`, made with a root alpine container because `appdata/db` is root-owned).
  2. Tag the old image: `docker tag ghcr.io/homarr-labs/homarr:latest homarr-rollback:<version>`.
  3. Run `docker compose pull && docker compose up -d`.
  - **Rollback:** set `image: homarr-rollback:v2.5.2` in `compose.yml`, restore the matching `backups/*.tgz` into `appdata/`, then `docker compose up -d`.
  - The startup log shows a Redis "Memory overcommit must be enabled" warning from Homarr's built-in Redis. It's harmless and has been there since install.
- `.env` holds `SECRET_ENCRYPTION_KEY`. **Back it up together with `appdata/`.** Without it, the saved integration credentials can't be decrypted.
- Port 7575 is published through Docker, which **bypasses ufw**. It's reachable from the LAN and tailnet, but not the internet, because the router doesn't forward it.

### 3.2 Uptime Kuma (monitoring)
- Image `louislam/uptime-kuma:2`, `network_mode: host`, data in `./data` (SQLite).
- Current monitors:

| Monitor | Type | Target |
|---|---|---|
| Minecraft Server | GameDig (Minecraft) | `127.0.0.1:25565` |
| Exit Node - Pi Reachable | Ping | `100.64.0.20` |
| Exit Node - Traffic via PI | HTTP keyword | `https://ifconfig.me/ip` must contain `198.51.100.20` |
| Dawarich | HTTP | `http://127.0.0.1:3000/api/v1/health` (changed 2026-10-19) |
| Homarr | HTTP | `http://127.0.0.1:7575` |
| GolfApp | HTTP | `http://127.0.0.1:8001` (added 2026-10-17) |
| Ship Tracker | HTTP | `http://127.0.0.1:8100/health` (added 2026-10-19; goes down if the ship feed stops, not only the page) |

- Status page: **`/status/home`**, which feeds the Homarr widget. It has all 7 monitors (2026-10-19). **When you add a monitor, also add it to this status page** or it won't show up in Homarr.
- Because it uses host networking, local services are checked at `127.0.0.1`.
- If the Pi's ISP changes its WAN IP, "Traffic via PI" will go red. Update the keyword when that happens.
- **Notifications:** "Phone (ntfy)" is on for **all monitors** and is "Default enabled", so new monitors get it too. It uses the same private topic as the health check (see 3.6). It pushes once when a monitor goes **down** (after 3 failed checks, about 3 min, because retries = 2) and once when it comes back **up**. It's silent while healthy. Test it from Settings → Notifications → Phone (ntfy) → Test.

### 3.3 Beszel (system metrics)
- **Hub** (`henrygd/beszel`, host network, :8090) and **agent** (`henrygd/beszel-agent`, host network).
- The local agent talks to the hub over a **Unix socket**, `./beszel_socket/beszel.sock`, so no TCP port is opened. In the Beszel UI, the system's host field is `/beszel_socket/beszel.sock`.
- The agent has the Docker socket mounted read-only, so it shows per-container CPU and RAM. CPU temperatures come from `coretemp`.
- `.env` holds `BESZEL_KEY`, the hub's **public** key (not secret). The hub's private key is `beszel_data/id_ed25519`.
- **Raspberry Pi agent:** installed as a binary systemd service on the Pi (`beszel-agent`), port **45876**. The hub reaches it over Tailscale at `100.64.0.20:45876`. The Pi has **no firewall** (ufw isn't installed). Logs: `journalctl -u beszel-agent` on the Pi.

### 3.4 Dawarich
- Compose project `docker` in `~/Desktop/docker/` with app, sidekiq, redis and postgis. Network `docker_dawarich` (172.18.0.0/16).
- No Homarr integration exists for it, so it's an App tile plus an Uptime Kuma HTTP monitor.
- **Health URL:** `http://127.0.0.1:3000/api/v1/health` (returns `{"status":"ok"}`). Since 1.16.0, `/` redirects to the sign-in page, so the updater, the 08:00 health check and the Uptime Kuma monitor use the health URL (changed 2026-10-19).
- **Extra database dumps** before risky updates: `docker exec dawarich_db pg_dump -U postgres -d dawarich_development -Fc > ~/dawarich-backups/dawarich-<version>-<date>.dump` (owner-only, ~8 MB). Restore into an empty database with `pg_restore`. A dump of 1.15.3 (6,174 points, 2026-10-07 → 2026-10-18) was taken on 2026-10-19 before the 1.16.0 update.

### 3.5 Minecraft
- `java -Xms6G -Xmx6G -XX:+UseG1GC -XX:+AlwaysPreTouch -jar server.jar nogui`. The heap was cut from 8 GB to **6 GB** on 2026-10-15, sized for a peak of 5 players on vanilla (backup of the old script: `start.sh.bak-8G`). `AlwaysPreTouch` claims about 6.7 GB at startup, so RAM use is flat from the start rather than creeping up for days.
- Started at boot by **crontab**: `@reboot sleep 30 && /bin/sh "/home/spencer/Desktop/MineCraft Server/minecraftServer.sh"` (full path: `~` doesn't expand inside quotes). That script creates the tmux session `minecraft` and runs `start.sh`.
- Console: `tmux attach -t minecraft`. Detach with `Ctrl-b` then `d`. Don't press Ctrl-C, which stops the server.
- `server.properties` has `enable-status=true`, which the Uptime Kuma GameDig monitor relies on.
- ufw allows port 25565.
- **How players connect:**
  - **Friends on the internet** use **`example.duckdns.org`**. The DNS name points at the home IP (3.8), and the **router port-forwards TCP 25565** to `192.168.1.179`. Replies leave via the home WAN thanks to rule 5209 (4.3).
  - **On the home LAN**, use **`192.168.1.179`**. Connecting to the DuckDNS name from inside only works if the router supports NAT loopback.
- **Exposed to the internet:** port 25565 is open to the world, and random scanners do try to join (e.g. `RandomPlayer123` from `203.0.113.x`). The **whitelist** (`white-list=true`, 7 players) and `online-mode=true` keep them out. **Keep the whitelist on.** Add players with `whitelist add <name>` in the console.
- **Backups:** nightly at 03:30, live, keeping up to 17 restore points (7 daily / 4 weekly / 6 monthly). Online players get a 5-min warning and a 10 s countdown. Restore with `sudo mc-backup restore` (see **3.11**).
- **Updates:** new stable releases are **not** applied automatically. You get a 📦 push; apply with `sudo homelab-updater apply minecraft` (0 players online; friends must update their game too). See **3.10**.
- **Auto-restart:** the watchdog (3.7) restarts Minecraft within about 15 min if the process dies. **Before stopping it on purpose,** run `touch ~/.homelab-maintenance` (remove it afterwards). Otherwise the watchdog will start it again.

### 3.6 Daily health check (ntfy)
- Runs **every day at 08:00 New York time** from the systemd timer `homelab-healthcheck.timer`. `Persistent=true`, so if the server was off at 8:00 it runs at the next boot. Source files are in `~/Desktop/Claud/healthcheck/`.
- **Checks:**
  - **System:** disk usage, free RAM, load, CPU temperature, failed systemd units, SSD SMART health, recent reboot, pending updates, and **reboot required** (`/var/run/reboot-required`, with the packages that need it).
  - **Network:** Tailscale up, exit node online, public IP is the Pi's `198.51.100.20`, rules 5208/5209, IP forwarding, ICMP redirects off, ufw active, gateway NAT rule, router ping, DNS, and **`example.duckdns.org` resolves to the current home IP** (home IP looked up via `curl --interface 192.168.1.179`; the stats line shows `Home: <ip>`).
  - **Tailnet:** Pi ping, Pi's Beszel agent port.
  - **Services:** every Docker container running and healthy, web UIs (Homarr, Uptime Kuma, Beszel, Dawarich, Plex), GolfApp on :8001 (⚠️ warning only, not a failure), Plex service, Minecraft tmux session and port, and any Uptime Kuma monitor that is currently down.
  - **Automation:**
    - the **Minecraft backup** (warns if the last good one is over 26 h old, fails over 72 h or if it never succeeded)
    - **updater activity** from its own history file: updated in the last 24 h (including GolfApp GitHub pulls), waiting for your approval, on hold, or failed, plus a ⚠️ if a GitHub pull failed
    - anything the **watchdog** restarted or failed to fix in the last 24 h
  - The stats line also shows the home IP, any updates and the backup age.
- **Notifications** go to a private ntfy.sh topic. The topic name is **only** in `/etc/homelab-healthcheck.conf` (root-only); see it with `sudo grep NTFY_URL /etc/homelab-healthcheck.conf`. Treat it like a password: anyone who knows it can read the reports and push to your phone. The same topic is used for the Uptime Kuma ntfy notification and is shown on the Homarr **Notifications** widget (3.1).
- **Pushes:**
  - **All good:** one "✅ all checks passed" push with stats.
  - **Warnings:** a ⚠️ push at priority 4.
  - **Failures:** a 🚨 push at priority 5. Claude Code (headless, `--model haiku`, **all tools disabled**) reads the report plus this README and writes a short "what's wrong, likely cause, first fix" summary. If Claude is unavailable, the raw list is sent instead.
- **Files:**
  - `/usr/local/bin/homelab-healthcheck` (the script)
  - `/etc/homelab-healthcheck.conf` (root-only: topic, expected IPs, disk)
  - `/etc/systemd/system/homelab-healthcheck.{service,timer}`
- **Commands:**
  - Run now (sends a push): `sudo systemctl start homelab-healthcheck`
  - Preview without sending: `sudo homelab-healthcheck --dry-run`
  - Next run time: `systemctl list-timers homelab-healthcheck.timer`
  - Logs: `journalctl -u homelab-healthcheck -n 50`
- **To update after editing the source:** run `sudo bash ~/Desktop/Claud/healthcheck/install.sh`. It doesn't overwrite an existing `/etc` config.
- **If the Pi's WAN IP changes,** update `EXPECTED_EXIT_IP` in `/etc/homelab-healthcheck.conf`, and also the Uptime Kuma keyword.
- **New Docker containers and new Uptime Kuma monitors are picked up automatically.**

### 3.7 Watchdog (auto-restart, every 15 min)
- `homelab-watchdog.timer` runs `/usr/local/bin/homelab-watchdog` every 15 minutes, as root. **It doesn't use Claude.** It only fixes what doesn't fix itself:

| Problem | Why nothing else handles it | Watchdog action |
|---|---|---|
| Minecraft not running | It only starts at boot (crontab `@reboot`) | Waits 60 s, then sends `cd … && ./start.sh` into tmux session `minecraft`, creating the session if needed |
| Minecraft running but port 25565 not answering for 2 runs | — | **Alert only.** Never killed automatically, because that could damage the world |
| Docker, Tailscale or Plex in systemd state **failed** | systemd gave up after its start limit | `systemctl reset-failed` + `start` |
| Plex active but `/identity` not answering for 2 runs | Hangs aren't crashes | `systemctl restart` Plex |
| Homarr or Beszel running but web UI dead for 2 runs | They have no Docker healthcheck | `docker restart` |
| Any container **unhealthy** for 2 runs | Docker never restarts unhealthy containers | `docker restart` |

- **Left alone on purpose:**
  - services that are stopped (inactive) and containers that are exited, because those were stopped deliberately
  - crashes, which Docker and systemd restart by themselves
  - the firewall, routing and disks, which the daily report covers
- **Pauses itself** while `/run/homelab-updating` exists. The updater (3.10) and `mc-backup restore` (3.11) set it while they deliberately stop services, so the watchdog doesn't "fix" them mid-job.
- **Limits:** at most **3 restart attempts per service per 6 h**. After that it sends one 🚨 "limit reached" push and stops trying. It skips its first 10 minutes after a boot, and runs never overlap (`flock`).
- **Pushes** (same ntfy topic) are sent only when something changes:
  - **🔧 "X was down, restarted"** (priority 4) when a fix works.
  - **🚨 "restart didn't help"** (priority 5), sent once per incident, when a fix fails.
  - **✅ "X is back up"** when it later recovers.
- **Maintenance mode:** `touch ~/.homelab-maintenance` pauses all repairs. This is useful before stopping Minecraft or Plex on purpose. Remove it with `rm ~/.homelab-maintenance`. It's ignored once it's older than 24 h, so it can't be forgotten forever.
- **Commands:**
  - Preview without changing anything: `sudo homelab-watchdog --dry-run`
  - Logs: `journalctl -t homelab-watchdog`
  - State (strike counters, attempts): `/var/lib/homelab-watchdog/`
- The **8 AM daily report** lists anything the watchdog restarted (⚠️) or failed to fix (🚨) in the previous 24 h.

### 3.8 DuckDNS: `example.duckdns.org` (Minecraft address for friends)
- **Friends join with `example.duckdns.org`** (port 25565 is the default), so the home IP changing no longer matters. The Homarr **Minecraft Server Status** widget uses the same address. That widget queries `api.mcsrvstat.us` from the internet, and its data is cached for about 5 min.
- Set up 2026-10-15 and verified: the name resolves to `203.0.113.10`, and `api.mcsrvstat.us` sees the server online (26.3) at that name. The account is on duckdns.org, where you signed in and claimed the subdomain `example`.
- `taken.duckdns.org` was already taken by someone else.
- **It must point at the HOME IP, not the Pi.** This server's traffic normally exits via the Pi (`198.51.100.20`), so a normal DuckDNS update would register the wrong IP. `duckdns-update` binds its request to the LAN IP (`curl --interface 192.168.1.179`), so rule 5209 sends it out the home WAN and DuckDNS sees the home IP (`203.0.113.10` at setup).
- **Files:**
  - `/usr/local/bin/duckdns-update`
  - `/etc/duckdns.conf` (root-only, holds the **token**; treat it like a password)
  - `duckdns-update.{service,timer}`, which runs 2 min after boot and then every 5 min
  - Sources are in `~/Desktop/Claud/duckdns/`. `install.sh` prompts for the token with hidden input.
- **Logs:** run `journalctl -t duckdns`. It's quiet when nothing changes, and logs "updated …" when the home IP changes or "FAILED" on errors.
- The **daily health check** fails if `example.duckdns.org` doesn't match the current home IP.
- **New token** (if it ever leaks): regenerate it on duckdns.org, then run `sudo rm /etc/duckdns.conf && sudo bash ~/Desktop/Claud/duckdns/install.sh`.

### 3.9 Plex
- snap `plexmediaserver` (1.43.x), web UI at http://192.168.1.179:32400/web. Claimed by the Plex account.
- **Library folder:** `~/Desktop/Plex_Server/Movies`. It was **empty** as of 2026-10-15, and will move to a new drive (see to-dos). The snap can read under `/home`. A drive mounted under `/mnt` or `/media` may need the snap's `removable-media` permission (`sudo snap connect plexmediaserver:removable-media`).
- **Firewall:** port 32400 is allowed **from the LAN only** (4.4). Before that rule existed, app.plex.tv showed *"unable to connect securely"*, because ufw was silently dropping it.
- **Samsung TV** (`192.168.1.153`, CU7000) uses the Plex app and streams directly over the LAN (see 2).
- **Remote Access (outside home) probably won't work:** plex.tv sees this server's public IP as the **Pi's** (`198.51.100.20`, because of the exit node), so a router port-forward at home won't line up. Away from home, use the Plex app over Tailscale instead. That also needs the optional Tailscale ufw rule in the to-dos.
- **Jellyfin is not installed.** On 2026-10-15 the Jellyfin TV app froze on its logo because there was no Jellyfin server. The decision was to use Plex.
- **Sizing for a future library** (a 2-hour film):
  - 720p: about 1–3 GB
  - 1080p WEB-DL: about **4–8 GB**
  - 1080p x265: about 2–4 GB
  - 1080p remux: about 20–40 GB
  - 4K WEB-DL: about 15–25 GB
  - 4K remux: about 50–80 GB

  With about 350 GB usable on the SSD, that's roughly 55–60 movies at 1080p, or about 115 using x265.
- **CPU:** transcoding (converting on the fly for a device that can't play the file directly) takes about 1 core per 1080p stream on the i7-4790K. Avoid 4K files unless the TV supports 4K, so it can play them without transcoding.

### 3.10 Updates: `homelab-updater` (daily 04:00) and `homelab-rollback`
- `homelab-updater.timer` runs daily at **04:00 New York time** (`Persistent=true`). Results show in the 8 AM report. **It doesn't use Claude.**

| Service | Policy | What happens when a new version appears |
|---|---|---|
| Homarr, Uptime Kuma, Beszel (hub + agent) | **auto** | Backup, update, health check, push **🆙 "Updated X: old → new"** |
| Dawarich (app, sidekiq, redis, postgis) | **ask** | Push **📦 "Update available"** once per new version. Apply with `sudo homelab-updater apply dawarich` |
| Minecraft (vanilla, stable releases only, no snapshots) | **ask** | Push 📦. Apply with `sudo homelab-updater apply minecraft`. It refuses while players are online (use `--force` to override). **Players must update their game to the same version.** |
| Plex | snap (updates itself about 4×/day) | The updater only notices the change and pushes 🆙 with the rollback command |
| GolfApp (`~/Desktop/GolfApp`) | **git** | Fast-forward pull of `main` from GitHub, run as `spencer`. Low-priority 🆙 push listing the new commits. **Skipped** (logged, nothing lost) if the clone is on another branch or has uncommitted edits. A failed pull sends ⚠️ and the 8 AM report warns. No backup or rollback, because GitHub is the source of truth. Pull now: `sudo homelab-updater apply golfapp`. See 3.12 |
| Ubuntu packages | unattended-upgrades (security) | The daily report flags pending updates and "reboot required" |

- **Every update** (auto or approved):
  1. Pauses the watchdog (`/run/homelab-updating`).
  2. **Stops the service and backs up its data:** bind dirs or Docker volumes for stacks; for Minecraft, the world plus jar plus settings (about 3.6 GB, which takes a few minutes).
  3. Tags the running images as `homelab-rollback:<svc>.<container>.<timestamp>`.
  4. Updates and **waits for it to be healthy:** all containers running or healthy and the web UI answering. For Minecraft, the port is up and the log shows the new version (up to 10 min for the world conversion).
  5. **If it's unhealthy, it rolls back automatically** (🚨/↩️ push).
  6. Keeps the last **3** backups per service (**2** for Minecraft) in `/var/backups/homelab/<svc>/<YYYYmmdd-HHMMSS>/` (root-only).
  - Minecraft downloads come straight from Mojang and are **SHA1-verified**.
- **Rollback:** `sudo homelab-rollback <svc>` restores the **latest backup's data plus the previous version**, then puts the service **on hold** so tomorrow's run doesn't redo the same update. Resume with `sudo homelab-updater unhold <svc>`.
  - A specific backup: `sudo homelab-rollback <svc> <YYYYmmdd-HHMMSS>`.
  - ⚠️ A rollback restores data **as of the update**. For Minecraft that means **anything built since the update is lost**; for Dawarich, any location points recorded since.
  - For Plex it runs `snap revert` plus `snap refresh --hold`.
- **Commands:**
  - Status (versions, holds, backups): `sudo homelab-updater status`
  - What's out of date (pulls images, changes nothing running): `sudo homelab-updater check`
  - Update one thing now: `sudo homelab-updater apply <svc>`. `--force` re-runs the whole backup and update even when it's current, which is a good way to test.
  - Logs: `journalctl -t homelab-updater`. The 8 AM report reads the updater's own history file, `/var/lib/homelab-updater/history.log` (`timestamp|message`), so test runs with a different state dir never count as real events.
- **Tested 2026-10-15** on Uptime Kuma:
  - A forced update (backup 617 KB, healthy in 11 s).
  - A manual rollback (data plus image restored, healthy in 10 s, hold and unhold).
  - A simulated failed update, which **rolled back automatically**.
  - The Minecraft download of 26.3 was SHA1-verified and byte-identical to the installed jar.

### 3.11 Minecraft world backups: `mc-backup` (restic, nightly 03:30)
- **What:** a **live, deduplicated** snapshot of `world/` plus `server.properties`, `whitelist.json`, `ops.json`, `banned-*.json` and `start.sh`, taken every night at **03:30 New York time** (`mc-backup.timer`, `Persistent=true`). That's before the 04:00 updater.
- **Player warning:** if anyone is online at 03:30, players get a gold chat message *"[Backup] Server backup in 5 minutes. You may notice a brief lag spike…"*. Then there's a **10-second countdown** on the action bar, then *"Backing up now"*, and afterwards *"Backup complete - thanks for your patience!"*. With nobody online it backs up immediately. `sudo mc-backup now` skips the warnings.
- **Live, so no downtime:** it sends `save-off` and `save-all flush` to the console, waits for *"Saved the game"*, takes the snapshot, then **always** sends `save-on` again (even if something fails). Saving is paused for about 20 s and players aren't disconnected.
- **Retention:** 7 daily, 4 weekly and 6 monthly restore points (`restic forget --prune` after each run). On **Sundays** it also runs an integrity check that reads 10% of the data.
- **Size:** much smaller than the world, because restic compresses the empty padding inside region files.
  - Tested 2026-10-15: the 3.52 GiB world was stored as **1.22 GiB**. The first backup took 23 s.
  - A second backup took 6 s and added **2 KB**.
  - Expect a few GB in total even after months.
- **Repository:** `/var/backups/minecraft-restic` (root-only, **on the same SSD**). This protects against griefing, corruption and bad updates, **not** against the SSD dying. Add the new drive as a second copy when it arrives (to-dos).
- **🔑 Password:** `/etc/mc-backup.pass` (root-only, random). **Without it, the backups can't be read.** View it with `sudo cat /etc/mc-backup.pass` and **keep a copy in a password manager**. Copying the repository to another drive is useless without it.
- **Commands:**
  - Restore points: `sudo mc-backup list`
  - Back up now: `sudo mc-backup` (warns online players 5 min ahead), or `sudo mc-backup now` (immediate, no warnings)
  - **Restore:** `sudo mc-backup restore latest`, or `sudo mc-backup restore <ID>` with an ID from `list`. It asks you to type `restore`, then:
    1. Warns players in chat, then stops the server.
    2. Restores into a temp folder and checks it.
    3. **Moves the current world aside** to `world.before-restore-<time>` (nothing is deleted; remove that folder yourself once you're happy).
    4. Starts the server and pushes ♻️.
    - The watchdog is paused during a restore.
  - Integrity: `sudo mc-backup check`. Size: `sudo mc-backup stats`. Logs: `journalctl -t mc-backup`.
- **Alerts:**
  - A failed backup sends a 🚨 push.
  - The 8 AM report shows `MC backup: Xh ago · snapshots=N size=…`. It warns if the last good backup is over 26 h old, and fails if it's over 72 h or has never succeeded.
- **Tested 2026-10-15** (sandbox repository, live server):
  - The `save-off` → flush → `save-on` sequence was confirmed in the server log.
  - Restoring to a temp folder gave **3,276 files, 3.52 GiB in 16 s, with 0 differences from the live world** and ownership preserved.
  - A bug where the include path didn't match was found and fixed in that test.
- **Separate from the updater's backups:** `homelab-updater apply minecraft` takes its own one-off full archive before a version upgrade (3.10).

### 3.12 GolfApp (friend's golf web app)
- **What:** Caddie Voice, a single-file web app (`index.html`) from **`a-friend/GolfApp`** on GitHub, owned by a friend. `SpencerMaginsky1` is a collaborator with push access. The friend's live copy is on Netlify; this server only runs a local copy for viewing and testing.
- **Runs as** `homelab-golf.service`: `/usr/local/bin/golf-serve` (Python's web server, but it **never serves hidden paths like `.git` and never lists folders**) on **port 8001, all interfaces**, as `spencer`, read-only, started at boot. Sources and installer: `~/Desktop/Claud/golf-server/`.
- **Open it at** http://192.168.1.179:8001 on the home LAN (PC, phone on Wi-Fi), or http://spencer-server:8001 from any tailnet device (iPhone away from home). ufw allows 8001 **only from the LAN and tailscale0** (4.4). The router doesn't forward it, so it's **not on the internet**. Plain HTTP, so once the app gains GPS, phones will block location here (GPS needs HTTPS). Test GPS on the Netlify site, or add HTTPS on the tailnet later with `tailscale serve`.
- **Clone:** `~/Desktop/GolfApp`, with git identity set repo-locally to the GitHub noreply address. GitHub login: `gh auth status` (account `SpencerMaginsky1`, HTTPS via the gh credential helper).
- **Kept current automatically** by the 04:00 updater (3.10). The web server reads the files directly, so a pull is live on :8001 straight away with no restart.
- **Working on it:** pull first, use a **branch plus pull request**, and never push to `main`, because every push to `main` goes live on the friend's Netlify site. The repo's own `CLAUDE.md` has the friend's rules: test before pushing (Indian Island → Start round → next hole → End round, no page errors) and write commit messages as a summary line plus bullets. Leave the clone on `main` with no uncommitted edits when you're done, or the nightly pull skips it.
- **Monitoring:** Uptime Kuma HTTP monitor "GolfApp" (down/up pushes; add it to the `home` status page so it also shows in Homarr's Kuma widget), the Homarr tile's status dot, and a ⚠️ in the 08:00 health check if it isn't answering. The watchdog does **not** restart it; systemd restarts it only if it crashes.
- **Commands:** `systemctl status homelab-golf` · `sudo homelab-updater apply golfapp` (pull now) · `journalctl -t homelab-updater | grep golfapp`.

### 3.13 Ship Tracker (live AIS map, added 2026-10-19)
- **What:** a live map of ships around New York City and Long Island (position, heading, speed, type, destination), from the free **aisstream.io** AIS feed. There's no radio on this server; the data comes over the internet.
- **Open it at** http://192.168.1.179:8100, or http://spencer-server:8100 over Tailscale. The port is published by Docker, so it skips ufw: it's reachable from the LAN and tailnet without a rule, and the router doesn't forward it, so it's not on the internet.
- **How it works:** a small Python app (`app.py`) holds one websocket to aisstream.io (the API key never leaves the server), keeps each ship's latest report for 60 min, and serves the map (`index.html`, Leaflet plus Esri dark tiles), `/api/ships` (JSON), `/health` and `/ping`. Ship type and destination arrive about every 6 min, so new ships show as "Other / unknown" at first. Ships are kept in memory only, so a restart empties the map for a few minutes.
- **Coverage:** the free feed only has ships that volunteer receivers hear. Coverage is good from NYC through western Long Island (both shores, to about Port Jefferson) and offshore, but there's almost nothing for eastern Long Island (Peconic, Montauk, the eastern Sound). The map's **"Open this view on MarineTraffic ↗"** button (added 2026-10-19) opens MarineTraffic at the same spot and zoom for those areas. It's only a link; MarineTraffic's data is paid and can't be pulled into this map. A local USB AIS receiver would fill the gap (not set up).
- **Files:** `~/Desktop/docker/ships/`: `app.py`, `index.html`, `Dockerfile`, `compose.yml`, `.env.example`, and `.env` (owner-only; holds `AISSTREAM_API_KEY` and `BBOX`). Nothing to back up except `.env`; ships are kept in memory only.
- **Area:** `BBOX=south,west,north,east` in `.env`. Currently `39.90,-74.30,41.35,-71.50` (widened 2026-10-19): all of Long Island and Long Island Sound up to the Connecticut shore, from Newark Bay out past Montauk and Block Island, and south to the offshore shipping lanes off the Jersey Shore. The first NYC-only box was `40.45,-74.30,40.88,-73.70`. After changing it, run `docker compose up -d` in that folder.
- **Container:** `ships` (image `homelab-ships:local`, python 3.13-alpine): read-only, no capabilities, non-root, 128 MB memory cap, Docker healthcheck on `/ping`.
- **Monitoring:** Uptime Kuma "Ship Tracker" checks `/health`, which returns 503 if the feed is disconnected or quiet for 15 min. It's on the `home` status page. The 08:00 health check covers it through its "every container healthy" check.
- **Updates:** **not** handled by `homelab-updater` (it's built locally). Refresh the base image now and then: `cd ~/Desktop/docker/ships && docker compose build --pull && docker compose up -d`.
- **Commands:** `docker logs ships` (feed connects and errors) · `curl -s localhost:8100/health`.

---

## 4. How traffic flows (the important, non-obvious part)

### 4.1 This server → internet: through the Pi exit node
```
tailscale set --exit-node=raspberrypi --exit-node-allow-lan-access=true
```
- **`--exit-node-allow-lan-access=true` is required.** Without it, Tailscale's routing table 52 sends replies to LAN devices into the tunnel. **SSH from the LAN drops instantly.**
- The setting is saved by Tailscale and survives reboots.

### 4.2 LAN devices → this server → Pi → internet (gateway mode)
This server is a "one-armed" gateway: it has a single NIC, on the same subnet as its clients.

**Per-client setup (manual, on each device you want tunneled):**
- Gateway: `192.168.1.179`
- DNS: `1.1.1.1` or `9.9.9.9`. Keeping `192.168.1.1` would send DNS lookups to the ISP outside the tunnel.
- **IPv4 only.** IPv6 comes straight from the ISP router and **bypasses** this gateway. Disable IPv6 on a client if leaks matter.

**What makes it work:**
1. **`/etc/sysctl.d/99-gateway.conf`** turns on `net.ipv4.ip_forward=1` and turns off `send_redirects` (all, default and enp2s0). Redirects must be off. Otherwise the server tells clients to "go straight to 192.168.1.1", which bypasses the tunnel.
2. **`/etc/ufw/before.rules`** has a block, marked `# --- LAN gateway via Tailscale exit node ---`, above `*filter`:
   - `nat POSTROUTING -s 192.168.1.0/24 -o tailscale0 -j MASQUERADE`. The Pi only accepts traffic from this server's Tailscale IP, so LAN addresses have to be rewritten.
   - `mangle FORWARD -o tailscale0 ... TCPMSS --clamp-mss-to-pmtu`. Tailscale's MTU is 1280 versus 1500 on the LAN. Without this, some HTTPS sites hang.
   - Original file backed up at `/etc/ufw/before.rules.bak-gateway`.
3. **ufw route rule**: `ufw route allow in on enp2s0 out on tailscale0 from 192.168.1.0/24`. The forward policy stays DROP, so this is the only forwarding path, and clients can't leak out through enp2s0.

### 4.3 Policy routing (tables 128 and 52)
```
5208: from all to 172.16.0.0/12 lookup main     # replies to Docker networks
5209: from 192.168.1.179 lookup 128              # LAN-IP-sourced traffic goes out the home WAN, not the tunnel
5210+ / 5270: Tailscale's own rules (table 52 = exit node)
```
- **Table 128** has `192.168.1.0/24 dev enp2s0` and `default via 192.168.1.1`. Rule **5209** makes anything sent *from* the LAN IP use the normal home connection. That keeps inbound connections (for example the router's port-forward to Minecraft) answered from the same IP they arrived on, instead of the replies going out through the Pi.
- Rule **5208** exists because of 5209. Containers on Docker bridges, such as Homarr, connect to `192.168.1.179:<port>`. The replies are sent *from* 192.168.1.179, and without 5208 table 128 would send them to the router instead of back to the bridge. Symptom: Homarr gets "connect timeout" on Uptime Kuma or Beszel.
- **Made persistent by** the NetworkManager dispatcher script **`/etc/NetworkManager/dispatcher.d/50-policy-routing`** (root:root 755). It runs on `enp2s0` up, DHCP renewals and reapply. It reads the current IP, gateway and subnet, then re-adds both rules at **fixed priorities 5208/5209**, so they always sit above Tailscale's. It logs with tag `policy-routing`.

### 4.4 Firewall (ufw) rules
| Rule | Why |
|---|---|
| `allow ssh` | SSH |
| `allow 25565` | Minecraft (from anywhere, because friends connect over the internet via the router's port-forward, TCP 25565 → 192.168.1.179) |
| `allow from 192.168.1.0/24 to any port 32400 proto tcp` | Plex from the LAN. Plex over Tailscale and the GDM discovery ports 32410–32414/udp are **not** allowed yet |
| `allow from 192.168.1.0/24 to any port 3001,8090` (two rules) | Uptime Kuma and Beszel from the LAN |
| `allow in on tailscale0 to any port 3001,8090` | Uptime Kuma and Beszel over Tailscale |
| `allow in on br-homarr to any port 3001,8090` | Homarr container → Uptime Kuma and Beszel |
| `allow from 192.168.1.0/24 to any port 8001 proto tcp` + `allow in on tailscale0 to any port 8001 proto tcp` | GolfApp from the LAN and tailnet (3.12) |
| `allow in on br-homarr to any port 8001 proto tcp` | Homarr container → GolfApp (its tile's status check) |
| `route allow in on enp2s0 out on tailscale0 from 192.168.1.0/24` | LAN gateway forwarding |

Ports published by Docker (dawarich 3000, Homarr 7575) **don't go through ufw**.

---

## 5. Health check (run after a reboot or when something seems off)
*Full command list: [COMMANDS.md](COMMANDS.md) §1.*
```bash
tailscale status | grep raspberrypi          # "active; exit node"
curl -4 -s ifconfig.me; echo                 # 198.51.100.20 = via Pi
ip rule | grep -E '520[89]'                  # both policy rules present
journalctl -t policy-routing -b              # "applied: ..." line from this boot
sysctl net.ipv4.ip_forward net.ipv4.conf.enp2s0.send_redirects   # 1 and 0
tmux ls                                      # minecraft session
systemctl list-timers 'homelab-*' mc-backup.timer duckdns-update.timer   # all 5 automation timers scheduled
sudo homelab-updater status                  # versions, holds, backups
sudo mc-backup list                          # Minecraft restore points (newest should be from ~03:30 today)
journalctl -t homelab-watchdog --since -24h  # anything the watchdog restarted
ls ~/.homelab-maintenance 2>/dev/null        # should NOT exist unless you're doing planned work
getent hosts example.duckdns.org            # must equal the home IP below
curl -4 -s --interface 192.168.1.179 ifconfig.me; echo   # home IP (203.0.113.10 at setup)
journalctl -t duckdns -n 5                   # updater: 'updated' / 'FAILED' lines only
docker ps --format '{{.Names}}\t{{.Status}}' # 9 containers up
systemctl is-active homelab-docs homelab-golf  # docs :8000 + GolfApp :8001 web servers
sudo ufw status verbose
```
Then open Homarr and check that the widgets load and everything in Uptime Kuma is green.

## 6. Troubleshooting
*The commands for every fix below are in [COMMANDS.md](COMMANDS.md), grouped by tool.*

| Symptom | Likely cause / fix |
|---|---|
| SSH drops when the exit node is turned on | LAN access is off. Run `sudo tailscale set --exit-node-allow-lan-access=true` (from the server's own console). |
| Server's public IP shows `203.0.113.10` | Exit node isn't active. Check `tailscale status`, and check that the Pi is online. |
| Homarr "connect timeout" to Uptime Kuma or Beszel | Rule 5208 missing, so run the dispatcher manually (below). Or the `br-homarr` ufw rule is missing. |
| Homarr Beszel "400 auth-with-password" | Use the Beszel **email** plus password. |
| A Kuma monitor shows 100% packet loss | Check the target IP for typos. The Pi is `100.64.0.20`. |
| A tunneled client loads some sites but not others | MSS clamp missing from `before.rules` (needs `sudo ufw reload`). |
| A new monitor doesn't show in the Homarr widget | Add it to the Kuma status page `home`. |
| Minecraft didn't start after reboot | Check `crontab -l` and `tmux ls`. Start it by hand with `/bin/sh "/home/spencer/Desktop/MineCraft Server/minecraftServer.sh"`. The watchdog also starts it 10–25 min after boot if cron didn't. |
| Minecraft (or another service) keeps coming back after you stopped it | That's the watchdog. Run `touch ~/.homelab-maintenance` before planned work, and `rm` it afterwards. |
| 🚨 "auto-restart limit reached" push | The watchdog tried 3 times in 6 h and gave up. Check `journalctl -t homelab-watchdog -n 30` and the service's own logs (for Minecraft: `tmux attach -t minecraft`). |
| Other devices or the TV can't reach Plex | ufw only allows Plex (32400) from the LAN. Check for blocks with `journalctl -k \| grep 'UFW BLOCK' \| grep 32400`. |
| Friends can't join `example.duckdns.org` | 1) `getent hosts example.duckdns.org` must equal the home IP (`curl -4 --interface 192.168.1.179 ifconfig.me`). If not, check `journalctl -t duckdns` and run `sudo duckdns-update`. 2) Check the router's port-forward (TCP 25565 → 192.168.1.179). 3) Check the player is on the whitelist. |
| You can't join via `example.duckdns.org` from home | The router doesn't do NAT loopback. Use `192.168.1.179` on the LAN. |
| DuckDNS points to the Pi's IP (`198.51.100.20`) | The updater went out via the exit node. It must use `--interface <LAN IP>`; check that rule 5209 exists (`ip rule`). |
| Homarr Minecraft widget shows offline but Uptime Kuma says up | It goes through the internet and the DuckDNS name, so check the DuckDNS row above. Changes also take up to ~5 min to show (mcsrvstat cache). |
| An auto-update broke something | `sudo homelab-rollback <svc>` restores the previous version plus data and holds it. Check `journalctl -t homelab-updater` for what changed. |
| 📦 "Update available" for Minecraft or Dawarich | Not applied on purpose. Read the release notes, then `sudo homelab-updater apply <svc>` (Minecraft: with 0 players online, and tell friends to update their game). |
| A service never updates any more | It's probably **on hold** after a rollback: run `sudo homelab-updater status`, then `sudo homelab-updater unhold <svc>`. |
| Need to undo griefing, corruption or a mistake in the world | `sudo mc-backup list`, pick the last good point, then `sudo mc-backup restore <ID>`. The current world is kept as `world.before-restore-*`. |
| 🚨 "Minecraft backup failed" | `journalctl -t mc-backup -n 30`. If it says saving wasn't confirmed, check the server is responsive (`tmux attach -t minecraft`). Saving is always switched back on. |
| GolfApp tile in Homarr is red, but http://192.168.1.179:8001 works | The `br-homarr` ufw rule for 8001 is missing (Homarr's pings get blocked: `journalctl -k \| grep 'UFW BLOCK' \| grep 8001`). Re-run `sudo bash ~/Desktop/Claud/golf-server/install.sh`. |
| GolfApp doesn't show your friend's latest changes | The 04:00 pull skips the clone if it's on another branch or has uncommitted edits: `journalctl -t homelab-updater \| grep golfapp`, then `git -C ~/Desktop/GolfApp status`. Pull now with `sudo homelab-updater apply golfapp`. |
| Daily report: "Failed systemd units: user@1000.service" | Your per-user systemd manager got stuck stopping after the last login session closed. The snap desktop helper's `xdg-document-portal` doesn't exit within Ubuntu's 5 s stop limit, so it was killed and marked failed. This happened on every logout. Fixed 2026-10-19 with `loginctl enable-linger spencer` (no sudo needed), which keeps the user manager running all the time. Check it with `loginctl show-user spencer -p Linger`. If it ever shows up again: `sudo systemctl reset-failed user@1000.service`. |
| No ntfy pushes at all | Check the topic in the app matches `sudo grep NTFY_URL /etc/homelab-healthcheck.conf`, and test with `curl -d hi ntfy.sh/<topic>`. |

Re-apply the routing rules by hand:
```bash
sudo /etc/NetworkManager/dispatcher.d/50-policy-routing enp2s0 up
```

## 7. Common tasks
*More in [COMMANDS.md](COMMANDS.md): updates and rollback §5, backups and restore §6, the Minecraft console §7, Docker §10.*

- **Update a service:** this is automatic for Homarr, Uptime Kuma and Beszel at 04:00. Otherwise run `sudo homelab-updater apply <svc>`, which backs up, updates, health-checks and rolls back if needed (3.10). Avoid a bare `docker compose pull && up -d`, because it skips the backup and rollback tag.
- **Add a service to monitoring:** add an Uptime Kuma monitor (use `127.0.0.1:<port>` for local services), add it to status page `home`, and optionally add a Homarr App tile using `http://192.168.1.179:<port>`.
- **Add another machine to Beszel:** Beszel → Add System → Binary → copy the command and run it on the machine. If you add it over Tailscale, use its `100.x` IP and port 45876.
- **Turn the exit node off temporarily:** `sudo tailscale set --exit-node=`. Turn it back on with `sudo tailscale set --exit-node=raspberrypi --exit-node-allow-lan-access=true`.
- **Backups worth keeping:** `~/Desktop/docker/` (all compose files, `.env` files and data dirs), `~/Desktop/MineCraft Server/world`, `/etc/ufw/before.rules`, `/etc/sysctl.d/99-gateway.conf`, `/etc/NetworkManager/dispatcher.d/50-policy-routing`, `/etc/homelab-healthcheck.conf` (holds the ntfy topic), `/etc/duckdns.conf` (holds the DuckDNS token; also keep the duckdns.org login). **`/etc/mc-backup.pass`** (the Minecraft backup password; without it the restic backups are unreadable). The Minecraft restic repository is `/var/backups/minecraft-restic`. Pre-update backups are in `/var/backups/homelab/` (last 3 per service; copy them off the machine if you want them to survive a disk failure). Sources and installers for all the homelab tools are in `~/Desktop/Claud/` (`healthcheck/`, `updater/`, `duckdns/`, `mc-backup/`, `docs-server/`, `golf-server/`). The GolfApp itself needs no backup, because GitHub has it.
- **Planned maintenance (stopping Minecraft or Plex on purpose):** run `touch ~/.homelab-maintenance` first, do the work, then `rm ~/.homelab-maintenance`.
- **Change the Minecraft RAM:** edit `-Xms`/`-Xmx` in `~/Desktop/MineCraft Server/start.sh` (currently 6G). Then, with no players online, run `stop` in the tmux console and start `./start.sh` again in the same session.

### Viewing the network diagram (and this README) from another computer
`homelab-docs.service` serves this folder with Python's built-in web server on port 8000, **bound to localhost only**. Nothing is exposed to the network and no ufw change is needed. It **starts at boot** and restarts if it crashes. It runs as `spencer` with read-only access to `/home`. (Before 2026-10-16 it was started by hand with `nohup`, which didn't survive reboots; after a reboot the tunnel gave *"channel 3: open failed: connect failed: Connection refused"*.)

1. **On the server**, check it's running: `systemctl status homelab-docs`. At the server itself, open http://127.0.0.1:8000/network-diagram.svg
2. **On your other computer**, open an SSH tunnel and leave that terminal open:
   ```bash
   ssh -L 8000:127.0.0.1:8000 spencer@192.168.1.179     # or spencer@spencer-server over Tailscale
   ```
   Then browse to **http://localhost:8000/network-diagram.svg**. `http://localhost:8000/` lists the folder.
3. **Closing the tunnel** (closing that terminal or typing `exit`) only closes the tunnel; the web server keeps running.
4. **Turn it off for good:** `sudo systemctl disable --now homelab-docs`. Turn it back on with `sudo systemctl enable --now homelab-docs`.
5. **Install or reinstall:** `sudo bash ~/Desktop/Claud/docs-server/install.sh` (it also stops any old hand-started `nohup` copy).
6. **"Connection refused" through the tunnel** means nothing is listening on port 8000 on the server. Check `systemctl status homelab-docs` and `journalctl -u homelab-docs -n 20`.

**Run the tunnel command on the PC**, not inside an SSH session on the server; otherwise the server tunnels to itself and the browser says "refused". (The GolfApp on 8001 doesn't need a tunnel: it's open to the LAN and tailnet, see 3.12.)

**On the phone:** `localhost` on the phone means the phone itself, so the tunnel approach doesn't work there. Share it to the tailnet only with `sudo tailscale serve --bg 8000`, then open `https://spencer-server.tailnet-name.ts.net/network-diagram.svg` with Tailscale connected. Stop sharing with `sudo tailscale serve --https=443 off`. (Not currently enabled.)

**Load:** next to nothing. Measured at 0.0% CPU while idle and about 19 MB of RAM, so it's fine to leave running.
**Why localhost only:** binding to `0.0.0.0` would make it reachable from the whole LAN and tailnet, and it would also need a ufw rule for port 8000. The SSH tunnel avoids both.

## 8. Undo the gateway / exit-node setup
```bash
sudo tailscale set --exit-node=
sudo rm /etc/sysctl.d/99-gateway.conf && sudo sysctl --system
sudo cp /etc/ufw/before.rules.bak-gateway /etc/ufw/before.rules
sudo ufw route delete allow in on enp2s0 out on tailscale0 from 192.168.1.0/24
sudo ufw reload
```
Leave the policy-routing dispatcher in place unless you also remove whatever needed rule 5209.

## 9. Open to-dos
- [ ] **Upgrade to Ubuntu 26.04.1 LTS.** 25.04 has been end of life since early 2026 and gets no security updates. Follow [UPGRADE-26.04.md](UPGRADE-26.04.md). It is done over SSH from the PC on the home LAN, inside `tmux`, with the exit node off. No monitor needed, but keep one and a USB keyboard handy in case it does not come back after the reboot.
- [ ] Reserve `192.168.1.179` for this server in the router's DHCP settings.
- [x] ~~Uptime Kuma status page `home`: add the Homarr and GolfApp monitors~~ (done 2026-10-17; all 6 monitors on the page).
- [x] ~~Install the updated health check (GolfApp check)~~ (done 2026-10-17).
- [ ] Optional: `enforce-whitelist=true` in Minecraft's `server.properties`, so removing someone from the whitelist also kicks them if they're online.
- [ ] **GolfApp (friend's repo):** course details for courses other than Indian Island (only it is built in; others depend on OpenStreetMap coverage). Ask which courses the owner plays; work on a branch plus pull request (3.12).
- [x] ~~Uptime Kuma notifications~~ (ntfy on all monitors, 2026-10-15).
- [ ] Beszel alerts (Pi offline, high temperature, and so on). Optional, since the health check and Uptime Kuma cover most of this.
- [ ] Optional: allow Plex over Tailscale (`ufw allow in on tailscale0 to any port 32400 proto tcp`) and GDM discovery (`32410,32412-32414/udp` from the LAN).
- [x] ~~Copy the Minecraft backup password into a password manager~~ (done 2026-10-15).
- [ ] When the new drive arrives, add a **second restic copy** of the Minecraft backups there (`restic copy` to a repository on that drive, run nightly), so an SSD failure doesn't take the backups with it.
- [x] ~~Install the 151 pending package updates~~ (done 2026-10-16; only `gnome-shell` asked for a reboot).
- [ ] **Seerr + Radarr** (on hold, researching). What was decided or found on 2026-10-15:
  - **Expected load:** Seerr :5055 (~150–250 MB RAM), Radarr :7878 (~200–350 MB). With a downloader added, also Prowlarr :9696 (~150–250 MB) and qBittorrent :8080 (~150–400 MB, 5–20% of a core while downloading). That's about **0.7–1.2 GB RAM** in total. Ports 5055/7878/9696/8080 were free.
  - **Radarr needs a download client plus indexers.** Options: qBittorrent + Prowlarr (torrents), SABnzbd + Prowlarr (Usenet, paid), or Seerr + Radarr only (library management, e.g. for ripped discs).
  - **⚠️ Legal/routing:** Docker traffic currently exits via the **Pi's** connection, so torrent activity would be attributed to whoever pays for the internet at the Pi's location. Use the home WAN (a policy rule like 5209 for the downloader's subnet), or a paid VPN with a kill switch. A VPN does **not** make downloading copyrighted content legal.
  - **Folder plan:** one `DATA_ROOT` (now `~/Desktop/Plex_Server`, later the new drive) holding `Movies/` and `downloads/` on the **same filesystem**, so Radarr hardlinks instead of copying. Set Radarr quality size limits (e.g. 1080p ≤ 10 GB).
- [ ] New drive for media: move `~/Desktop/Plex_Server/Movies`, then update the Plex library path. The old WD My Passport (Mac HFS+, 128 GB of 2011–2014 data, 4 unreadable metadata sectors) needs a Mac before it can be reused.
- [ ] Consider restricting the Pi's Beszel agent to listen only on its Tailscale IP.
- [ ] Optional: a dedicated, non-admin Beszel user for Homarr.
- [ ] **Homarr → Plex widgets** ("Media server streams", plus optionally "Media releases"). Steps:
  1. `sudo ufw allow in on br-homarr to any port 32400 proto tcp comment 'homarr -> plex'`. Homarr's container (172.19.x) is currently blocked; the kernel log shows `UFW BLOCK IN=br-homarr DPT=32400`.
  2. Get the token: `sudo grep -oP 'PlexOnlineToken="\K[^"]+' "/var/snap/plexmediaserver/common/Library/Application Support/Plex Media Server/Preferences.xml"`. Paste it only into Homarr; treat it like a password.
  3. In Homarr, go to Management → Integrations → Plex: URL `http://192.168.1.179:32400` plus the token, then Test and Save.
  4. On the board, choose Add item → Media server streams → the Plex integration. The widget stays empty until something is playing.
  5. Add the new ufw rule to the table in 4.4.
- [x] ~~Homarr widgets: Beszel Grid, Notifications (ntfy), Minecraft, Weather, Clock~~ (2026-10-15).
- [ ] More Homarr widgets worth adding: Bookmarks (router `192.168.1.1`, Tailscale admin, duckdns.org), Notebook (whitelist, server address), Releases (update tracking for Homarr, Kuma, Beszel and Dawarich). Skip "Docker stats": it needs the Docker socket, which is root-equivalent.
