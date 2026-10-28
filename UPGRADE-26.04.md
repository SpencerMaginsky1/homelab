# Upgrade plan: Ubuntu 25.04 → 26.04.1 LTS

Written 2026-10-16, updated 2026-10-20 to be done **over SSH from the main PC** (no monitor needed). **DONE 2026-10-20**: the server is on Ubuntu 26.04.1 LTS.

> **What happened (2026-10-20):** the release upgrade itself went fine (15:18 reboot into 26.04, all checks passed). During step 4.1's Docker/Tailscale update, the new **kernel 7.0** threw 117 SATA "host bus error" exceptions on the SSD link (`ata4`, Intel 9-series AHCI) and the server crashed at 15:23, leaving `docker-ce` half-configured. It came back on 7.0 at 15:36 (88 more errors), was switched to the old **6.14 kernel** with `grub-reboot` at 15:40, and has had 0 errors since. Recovery: `dpkg --configure -a` finished Docker, 6.14 was pinned as `GRUB_DEFAULT` and marked manual, and the exit node came back on with port 1022 closed. SMART passed (0 read/CRC errors, 100% life), so the drive is fine; it's the 7.0 driver. The only file hit by the crash was `/var/lib/apt/extended_states`, which was rewritten cleanly, and `dpkg --verify` found no changed files. Getting 7.0 working is a to-do in README §9.

**Why:** 25.04 (Plucky) is **end of life**, so it gets no more security updates. Minecraft is open to the internet, so the server should be on a supported release. 26.04 is an **LTS**, supported until 2031, so this is the last release upgrade for years.

**The path:** `do-release-upgrade -c` on 2026-10-16 offers **26.04.1 LTS directly**, so there's no stop at 25.10.

**What the server looked like at planning time:**

| | |
|---|---|
| Boot | UEFI, `grub-efi-amd64-signed`, `/boot/efi` 1.1 GB with 1% used. Disk 7% used, 405 GB free |
| Kernel | 6.14.0-37 running. The old 6.14.0-29 is still installed but no longer in any repo |
| Third-party apt repos | **Docker** (`docker-ce` 29.2.1, `containerd.io`, compose plugin) and **Tailscale** (1.104.1), both pinned to `plucky` |
| From Ubuntu | OpenJDK 25 (Minecraft), restic 0.17.3, Python 3.13, ufw (nf_tables), NetworkManager, Samba, OpenSSH, GNOME desktop |
| Snaps | Plex plus desktop snaps. Snaps aren't touched by the upgrade |
| Not packaged | Claude CLI in `~/.local/bin` (used by the health check). Not affected |

**Expected time:** 1–2 hours in total, most of it downloading and unpacking. **Downtime:** Minecraft, Plex and the dashboards are down for roughly 45–90 min.

**When:** in the daytime, with nobody playing. **Not between 03:00 and 08:30**, when the backup, updater and health check timers run.

**How:** from the Windows PC over SSH on the **home network** (`ssh spencer@192.168.1.179`), **not** over Tailscale, because the upgrade restarts Tailscale partway through. Everything runs inside `tmux`, so a dropped connection doesn't interrupt the upgrade. **No monitor needed**, but keep a monitor cable and a **USB keyboard** where you can grab them: you only need them if the server doesn't come back on the network after the final reboot (see *If something goes wrong*).

---

## Risks and how this plan handles them

| Risk | Handling |
|---|---|
| SSH drops mid-upgrade and leaves a half-upgraded system | The upgrade runs inside **`tmux`** (step 3.1), so it keeps going if SSH drops; reconnect and `tmux attach -t upgrade`. A second SSH window and the upgrader's backup SSH on port 1022 (opened for the LAN in step 2.4) are spare ways in. |
| The SSH session runs over Tailscale, which gets upgraded and restarted | Connect over the **home LAN** (`192.168.1.179`), never `spencer-server` or `100.x` (step 2.5). |
| Package downloads stall because the server's internet goes through the exit node while Tailscale is being upgraded | **Exit node off** for the upgrade (step 2.4), back on in step 4.3. |
| Server doesn't come back on the network after the reboot, so SSH can't reach it | That's the one case that needs the **monitor and USB keyboard**. See *If something goes wrong*. |
| `/etc/ufw/before.rules` gets replaced, losing the LAN-gateway NAT and MSS clamp (README 4.2) | When asked about a modified config file, **keep your version (`N`)**. `/etc` is backed up in step 1.3, and step 4.3 checks the block is still there. |
| Docker and Tailscale repos get **disabled** by the upgrader, so they'd stop getting updates | Step 4.1 points them at `resolute` (26.04's codename) and re-enables them. |
| A Docker upgrade restarts containers, and Dawarich's Postgres gets a new Docker version | The containers are already backed up (step 1.3). Images aren't changed by this, only the Docker engine. |
| Minecraft world damaged by a hard stop | Stop it cleanly first (step 2.2), with a fresh backup just before. |
| The watchdog "fixes" services that are deliberately stopped | Maintenance flag (step 2.1). It expires after 24 h. |
| Policy routing (5208/5209) or the exit node missing after reboot | They're restored automatically (the dispatcher script and Tailscale prefs). Step 4.3 checks them. |
| Something is badly broken afterwards | **A release upgrade can't be undone in place.** The fallback is a clean 26.04 install restored from the backups in step 1, so the off-machine copy (step 1.4) is the safety net. |

---

## 1. The day before: backups and a "before" record

- [x] **1.1 Bring 25.04 fully up to date and clean** _(done 2026-10-20: 0 updates pending, dpkg clean, no reboot needed. `autoremove` doesn't actually remove the old 6.14.0-29 kernel, only `grub-pc-bin`; both are left for the release upgrade to clean up)_
  ```bash
  sudo apt update && sudo apt full-upgrade -y
  sudo apt autoremove --purge -y          # also removes the orphaned 6.14.0-29 kernel
  sudo dpkg --audit && echo dpkg-clean    # must print dpkg-clean
  ```
  If the update needed a reboot, reboot now and check everything is back up (README §5).

- [x] **1.2 Save a "before" record** _(done 2026-10-20 14:42, 9 files in `~/upgrade-2604/before/`)_ to compare against afterwards
  ```bash
  mkdir -p ~/upgrade-2604/before && cd ~/upgrade-2604/before
  sudo ufw status verbose          > ufw.txt
  ip rule                          > ip-rule.txt
  ip route show table 128          > table128.txt
  sudo iptables-save               > iptables.txt
  docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' > docker.txt
  systemctl list-timers --all --no-pager > timers.txt
  tailscale debug prefs            > tailscale-prefs.json
  crontab -l                       > crontab.txt
  dpkg -l                          > packages.txt
  ```

- [x] **1.3 Back up everything a reinstall would need** _(done 2026-10-20 14:44: all 4 archives verified, Minecraft snapshot 3896e7f3)_
  ```bash
  touch ~/.homelab-maintenance                            # stop the watchdog restarting the apps mid-backup
  sudo mc-backup now                                      # fresh Minecraft restore point
  sudo tar czf ~/upgrade-2604/etc.tgz /etc                # all system config (ufw, sysctl, dispatcher, /etc/*.conf, mc-backup.pass, duckdns token)
  cd ~/Desktop/docker && docker compose stop && (cd homarr && docker compose stop) && (cd uptime-kuma && docker compose stop) && (cd beszel && docker compose stop)
  sudo tar czf ~/upgrade-2604/docker-dirs.tgz -C ~/Desktop docker
  sudo tar czf ~/upgrade-2604/docker-volumes.tgz /var/lib/docker/volumes   # Dawarich's Postgres and other named volumes
  docker start $(docker ps -aq)                           # bring them back up for now
  sudo tar czf ~/upgrade-2604/mc-restic.tgz /var/backups/minecraft-restic   # Minecraft backups, for the PC copy (about 1.3 GB)
  sudo chown spencer: ~/upgrade-2604/*.tgz && chmod 600 ~/upgrade-2604/*.tgz
  rm -f ~/.homelab-maintenance
  ls -lh ~/upgrade-2604/
  ```
  The apps are down for 1–2 minutes. `etc.tgz` and `docker-dirs.tgz` hold secrets (ntfy topic, DuckDNS token, `mc-backup.pass`, the `.env` files and Beszel's key), so treat them like passwords.

- [x] **1.4 Copy the backups off the machine.** _(done 2026-10-20 14:49 to `C:\Users\Spencer Maginsky\server-backup-2604`, sizes match exactly)_ There's no second drive yet, so use the Windows PC. From PowerShell on the PC:
  ```powershell
  mkdir "$HOME\server-backup-2604"
  scp spencer@192.168.1.179:~/upgrade-2604/*.tgz "$HOME\server-backup-2604"
  scp -r spencer@192.168.1.179:/home/spencer/Desktop/Claude "$HOME\server-backup-2604"
  ```
  Keep the quotes and leave off the trailing `\`: the Windows user folder has a space in it, which otherwise breaks scp's path.
  The `*.tgz` includes `mc-restic.tgz`, the Minecraft restic repository (about 1.3 GB, made in step 1.3). The world itself is in there.

- [ ] **1.5 Tell your Minecraft friends** about the downtime window.

---

## 2. Right before: quiet the server

- [x] **2.1 Pause the watchdog** _(done 2026-10-20 14:56)_
  ```bash
  touch ~/.homelab-maintenance
  ```
- [x] **2.2 Stop Minecraft cleanly.** _(done 14:56, 0 players, all worlds saved)_ Make sure nobody is online, then:
  ```bash
  tmux attach -t minecraft      # type: stop   … wait for the server to exit, then Ctrl-b d
  ```
- [x] **2.3 Make sure no timer job will fire mid-upgrade** _(done 14:58)_
  ```bash
  sudo systemctl stop homelab-updater.timer mc-backup.timer homelab-healthcheck.timer
  ```
  Leave DuckDNS and the watchdog alone. The watchdog is paused by the flag.

- [x] **2.4 Turn off the exit node, and open the upgrader's backup SSH port to the LAN**
  ```bash
  sudo tailscale set --exit-node=                   # server's internet now goes straight out the home router
  curl -4 -s ifconfig.me; echo                      # now shows the HOME IP (203.0.113.10), not the Pi's
  sudo ufw allow from 192.168.1.0/24 to any port 1022 proto tcp comment 'upgrade backup ssh (temporary)'
  ```
  Devices you've set up to use the server as their gateway ("tunneled LAN clients") lose internet until step 4.3. Switch them back to the router for now if they need it.

- [x] **2.5 Check your SSH setup from the PC.** _(done: 3 LAN SSH sessions from 192.168.1.159; exit node off, public IP = home)_ Use the LAN address, not Tailscale:
  ```powershell
  ssh spencer@192.168.1.179
  ```
  Open a **second** PowerShell window and SSH in the same way. Leave it logged in as a spare.

---

## 3. The upgrade

- [x] **3.1 Start it inside tmux** (in the first SSH window)
  ```bash
  tmux new -s upgrade
  sudo do-release-upgrade
  ```
  - It warns that you're running over SSH and asks *"Continue running under SSH?"*: **`y`**.
  - It says it's starting a backup SSH daemon on **port 1022**: press **Enter**. Step 2.4 opened that port to the LAN, so if normal SSH breaks you can use `ssh -p 1022 spencer@192.168.1.179`.
  - **If the connection drops:** reconnect (`ssh spencer@192.168.1.179`, or `-p 1022`) and run `tmux attach -t upgrade`. The upgrade keeps running while you're disconnected. **Don't start a second `do-release-upgrade`.**
  - You can detach on purpose with **Ctrl-b d** and reattach the same way.

- [x] **3.2 Answer the prompts**
  - *"Third party sources disabled"*: **OK.** Step 4.1 fixes this.
  - *"Do you want to start the upgrade?"*: review the **remove** list. Old kernels and libraries are fine to remove. If it wants to remove **`docker-ce`, `containerd.io`, `tailscale`, `openjdk-25-jre-headless`, `restic`, `ufw` or `network-manager`**, answer **No** and investigate first.
  - *"Configuration file … modified … install the package maintainer's version?"*: **`N` (keep yours)** for anything you customised, especially **`/etc/ufw/before.rules`**, `/etc/ssh/sshd_config` and `/etc/samba/smb.conf`. If unsure, choose `D` to see the diff; keeping yours is the safe default.
  - *"Restart services without asking?"*: **Yes.**
  - *"Remove obsolete packages?"*: **Yes**, unless the list includes anything named above.
  - *"Restart required"*: **Yes**, reboot. Your SSH sessions close; that's expected.

- [x] **3.3 Reconnect after the reboot.** Give it **3–5 minutes**, then from the PC:
  ```powershell
  ping 192.168.1.179
  ssh spencer@192.168.1.179
  ```
  If it still doesn't answer after **10 minutes**, it's time for the monitor and USB keyboard. See *If something goes wrong* ("It won't boot" / "No network after boot").

---

## 4. After the reboot

- [x] **4.1 Re-enable the Docker and Tailscale repos for 26.04**
  ```bash
  lsb_release -ds                                   # Ubuntu 26.04.1 LTS
  ls /etc/apt/sources.list.d/                       # see what the upgrader renamed or disabled
  ```
  Edit both repo files so the suite is **`resolute`** instead of `plucky`, and uncomment them if the upgrader commented them out. Also delete any `*.distUpgrade` / `*.save` leftovers once you're happy.
  ```bash
  sudo sed -i 's/plucky/resolute/' /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/tailscale.list
  sudo apt update                                   # must show download.docker.com and pkgs.tailscale.com with no errors
  sudo apt full-upgrade -y                          # moves Docker and Tailscale to their 26.04 builds
  ```
  If Docker or Tailscale doesn't publish a `resolute` repo yet, `apt update` will say so. Leave that file on `plucky` for now; the old packages keep working.

- [x] **4.2 Basics**
  ```bash
  uname -r                                          # new 26.04 kernel
  systemctl --failed                                # ideally 0
  sudo dpkg --audit && echo dpkg-clean
  [ -f /var/run/reboot-required ] && cat /var/run/reboot-required.pkgs   # reboot again if anything is listed
  ```

- [x] **4.3 Network: the fragile part.** First turn the exit node back on and close the temporary SSH port:
  ```bash
  sudo tailscale set --exit-node=raspberrypi --exit-node-allow-lan-access=true
  sudo ufw delete allow from 192.168.1.0/24 to any port 1022 proto tcp
  ```
  Then check:
  ```bash
  grep -c 'LAN gateway via Tailscale exit node' /etc/ufw/before.rules   # must be 1
  sudo ufw status verbose | diff - ~/upgrade-2604/before/ufw.txt && echo ufw-same
  ip rule | diff - ~/upgrade-2604/before/ip-rule.txt && echo rules-same
  journalctl -t policy-routing -b                   # "applied: ..." line
  sysctl net.ipv4.ip_forward net.ipv4.conf.enp2s0.send_redirects   # 1 and 0
  tailscale status | grep raspberrypi               # active; exit node
  curl -4 -s ifconfig.me; echo                      # 198.51.100.20 (the Pi)
  getent hosts example.duckdns.org                 # home IP
  curl -4 -s --interface 192.168.1.179 ifconfig.me; echo           # same home IP
  ```
  If the `before.rules` block is gone, restore it from the backup: `sudo tar xzf ~/upgrade-2604/etc.tgz -C / etc/ufw/before.rules && sudo ufw reload`.

- [x] **4.4 Services**
  ```bash
  docker ps --format '{{.Names}}\t{{.Status}}'     # all 9 up, healthchecks "healthy"
  java -version                                     # OpenJDK 25 (or newer)
  tmux ls                                           # minecraft session, started by @reboot
  snap services plexmediaserver
  systemctl status homelab-docs homelab-golf smbd ssh --no-pager | grep Active
  for p in 7575 3001 8090 3000/api/v1/health 32400/web/index.html 8000/ 8001/ 8100/health; do curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:$p; done
  ```
  Then check the Minecraft log shows "Done", and join the server yourself.

- [x] **4.5 Automation**
  ```bash
  rm ~/.homelab-maintenance
  sudo systemctl start homelab-updater.timer mc-backup.timer homelab-healthcheck.timer
  systemctl list-timers 'homelab-*' mc-backup.timer duckdns-update.timer   # all 5
  sudo homelab-watchdog --dry-run
  sudo homelab-updater status
  sudo mc-backup now && sudo mc-backup check        # proves the new restic still reads the repository
  claude --version                                  # the health check's AI summary needs this
  sudo systemctl start homelab-healthcheck          # sends a real report to your phone; expect ✅
  ```

- [ ] **4.6 By eye:** Homarr widgets load, everything in Uptime Kuma is green, Beszel shows both machines, and the Samsung TV plays from Plex.

---

## 5. Clean up and record

- [x] Update README.md: the OS in the Tailscale table (§1) and the "Last verified" line. Tick the to-do in §9. Then push the docs to GitHub: `~/Desktop/Claude/github/sync-repos.sh --push "Ubuntu 26.04 upgrade done"`.
- [x] `sudo ufw status | grep 1022`: must print nothing (the temporary rule from step 2.4 is gone).
- [ ] `sudo apt autoremove --purge`, after you've booted the new kernel at least once.
- [x] (done 2026-10-27) After a week with no problems, delete `~/upgrade-2604/` on the server. Keep the copy on the PC until the new drive is set up.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| The upgrade stops with an error partway | Don't reboot. Run `sudo dpkg --configure -a`, then `sudo apt -f install`, then `sudo apt full-upgrade`. Logs are in `/var/log/dist-upgrade/`. |
| It won't boot | At the GRUB menu (hold **Shift** or tap **Esc**), choose *Advanced options*, then the previous kernel. Once booted, fix forward with `sudo apt full-upgrade`. |
| Server doesn't answer `ping` or SSH 10 min after the reboot | Plug in the **monitor and USB keyboard**. If you see a login screen, log in and follow "No network after boot". If it's stuck before that, follow "It won't boot". |
| No network after boot | From the console: `nmcli dev status`, `sudo systemctl restart NetworkManager`, then `sudo /etc/NetworkManager/dispatcher.d/50-policy-routing enp2s0 up`. |
| LAN SSH dies when the exit node is turned back on (step 4.3) | Use the monitor and keyboard, or the spare SSH window if it's still alive: `sudo tailscale set --exit-node-allow-lan-access=true` (README §6). Step 4.3 already sets this, so it shouldn't happen. |
| SSH drops during the upgrade | Reconnect (`ssh spencer@192.168.1.179`, or `-p 1022`) and `tmux attach -t upgrade`. If `tmux` says there's no session and the upgrade isn't running (`pgrep -a do-release`), see "The upgrade stops with an error partway". |
| A Docker container won't start | `docker logs <name>`. If the data is the problem, stop the stack and restore from `docker-dirs.tgz` / `docker-volumes.tgz`. |
| Minecraft won't start | `tmux attach -t minecraft` and read the error. Check `java -version`. If OpenJDK 25 was removed: `sudo apt install openjdk-25-jre-headless`. |
| Badly broken | Do a clean install of 26.04, then restore `/etc` pieces from `etc.tgz` (not the whole of `/etc`), Docker data from the tarballs, Minecraft from restic, and re-run each `install.sh` in `~/Desktop/Claude`. README.md is the rebuild guide. |
