# Upgrade plan: Ubuntu 25.04 → 26.04.1 LTS

Written 2026-10-16. **Not done yet.** Tick the boxes as you go.

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

**When:** in the daytime, at the machine, with nobody playing. **Not between 03:00 and 08:30**, when the backup, updater and health check timers run.

---

## Risks and how this plan handles them

| Risk | Handling |
|---|---|
| SSH drops mid-upgrade and leaves a half-upgraded system | Do it **at the server's own keyboard and screen**. If you must use SSH, run it inside `tmux` (step 3.1). |
| `/etc/ufw/before.rules` gets replaced, losing the LAN-gateway NAT and MSS clamp (README 4.2) | When asked about a modified config file, **keep your version (`N`)**. `/etc` is backed up in step 1.3, and step 4.3 checks the block is still there. |
| Docker and Tailscale repos get **disabled** by the upgrader, so they'd stop getting updates | Step 4.1 points them at `resolute` (26.04's codename) and re-enables them. |
| A Docker upgrade restarts containers, and Dawarich's Postgres gets a new Docker version | The containers are already backed up (step 1.3). Images aren't changed by this, only the Docker engine. |
| Minecraft world damaged by a hard stop | Stop it cleanly first (step 2.2), with a fresh backup just before. |
| The watchdog "fixes" services that are deliberately stopped | Maintenance flag (step 2.1). It expires after 24 h. |
| Policy routing (5208/5209) or the exit node missing after reboot | They're restored automatically (the dispatcher script and Tailscale prefs). Step 4.3 checks them. |
| Something is badly broken afterwards | **A release upgrade can't be undone in place.** The fallback is a clean 26.04 install restored from the backups in step 1, so the off-machine copy (step 1.4) is the safety net. |

---

## 1. The day before: backups and a "before" record

- [ ] **1.1 Bring 25.04 fully up to date and clean**
  ```bash
  sudo apt update && sudo apt full-upgrade -y
  sudo apt autoremove --purge -y          # also removes the orphaned 6.14.0-29 kernel
  sudo dpkg --audit && echo dpkg-clean    # must print dpkg-clean
  ```
  If the update needed a reboot, reboot now and check everything is back up (README §5).

- [ ] **1.2 Save a "before" record** to compare against afterwards
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

- [ ] **1.3 Back up everything a reinstall would need**
  ```bash
  sudo mc-backup now                                      # fresh Minecraft restore point
  sudo tar czf ~/upgrade-2604/etc.tgz /etc                # all system config (ufw, sysctl, dispatcher, /etc/*.conf, mc-backup.pass, duckdns token)
  cd ~/Desktop/docker && docker compose stop && (cd homarr && docker compose stop) && (cd uptime-kuma && docker compose stop) && (cd beszel && docker compose stop)
  sudo tar czf ~/upgrade-2604/docker-dirs.tgz -C ~/Desktop docker
  sudo tar czf ~/upgrade-2604/docker-volumes.tgz /var/lib/docker/volumes   # Dawarich's Postgres and other named volumes
  docker start $(docker ps -aq)                           # bring them back up for now
  sudo chown spencer: ~/upgrade-2604/*.tgz
  ls -lh ~/upgrade-2604/
  ```
  `etc.tgz` holds secrets (the ntfy topic, DuckDNS token and `mc-backup.pass`), so treat the file like a password.

- [ ] **1.4 Copy the backups off the machine.** There's no second drive yet, so use the Windows PC. From PowerShell on the PC:
  ```powershell
  mkdir $HOME\server-backup-2604
  scp spencer@192.168.1.179:~/upgrade-2604/*.tgz $HOME\server-backup-2604\
  scp -r spencer@192.168.1.179:/home/spencer/Desktop/Claud $HOME\server-backup-2604\
  ```
  Also copy the Minecraft restic repository. It's root-only, so first make a readable copy on the server: `sudo tar czf ~/upgrade-2604/mc-restic.tgz /var/backups/minecraft-restic && sudo chown spencer: ~/upgrade-2604/mc-restic.tgz` (about 1.3 GB), then `scp` it the same way. The world itself is in there.

- [ ] **1.5 Tell your Minecraft friends** about the downtime window.

---

## 2. Right before: quiet the server

- [ ] **2.1 Pause the watchdog**
  ```bash
  touch ~/.homelab-maintenance
  ```
- [ ] **2.2 Stop Minecraft cleanly.** Make sure nobody is online, then:
  ```bash
  tmux attach -t minecraft      # type: stop   … wait for the server to exit, then Ctrl-b d
  ```
- [ ] **2.3 Make sure no timer job will fire mid-upgrade**
  ```bash
  sudo systemctl stop homelab-updater.timer mc-backup.timer homelab-healthcheck.timer
  ```
  Leave DuckDNS and the watchdog alone. The watchdog is paused by the flag.

---

## 3. The upgrade

- [ ] **3.1 Start it from the server's console** (or inside `tmux new -s upgrade` if over SSH)
  ```bash
  sudo do-release-upgrade
  ```
  If you're on SSH, it offers a backup SSH daemon on port 1022. ufw blocks that port, which is fine; the tmux session is what protects you. If SSH drops, log back in and run `tmux attach -t upgrade`.

- [ ] **3.2 Answer the prompts**
  - *"Third party sources disabled"*: **OK.** Step 4.1 fixes this.
  - *"Do you want to start the upgrade?"*: review the **remove** list. Old kernels and libraries are fine to remove. If it wants to remove **`docker-ce`, `containerd.io`, `tailscale`, `openjdk-25-jre-headless`, `restic`, `ufw` or `network-manager`**, answer **No** and investigate first.
  - *"Configuration file … modified … install the package maintainer's version?"*: **`N` (keep yours)** for anything you customised, especially **`/etc/ufw/before.rules`**, `/etc/ssh/sshd_config` and `/etc/samba/smb.conf`. If unsure, choose `D` to see the diff; keeping yours is the safe default.
  - *"Restart services without asking?"*: **Yes.**
  - *"Remove obsolete packages?"*: **Yes**, unless the list includes anything named above.
  - *"Restart required"*: **Yes**, reboot.

---

## 4. After the reboot

- [ ] **4.1 Re-enable the Docker and Tailscale repos for 26.04**
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

- [ ] **4.2 Basics**
  ```bash
  uname -r                                          # new 26.04 kernel
  systemctl --failed                                # ideally 0
  sudo dpkg --audit && echo dpkg-clean
  [ -f /var/run/reboot-required ] && cat /var/run/reboot-required.pkgs   # reboot again if anything is listed
  ```

- [ ] **4.3 Network: the fragile part**
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

- [ ] **4.4 Services**
  ```bash
  docker ps --format '{{.Names}}\t{{.Status}}'     # all 8 up, healthchecks "healthy"
  java -version                                     # OpenJDK 25 (or newer)
  tmux ls                                           # minecraft session, started by @reboot
  snap services plexmediaserver
  systemctl status homelab-docs homelab-golf smbd ssh --no-pager | grep Active
  for p in 7575 3001 8090 3000 32400/web/index.html 8000/ 8001/; do curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:$p; done
  ```
  Then check the Minecraft log shows "Done", and join the server yourself.

- [ ] **4.5 Automation**
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

- [ ] Update README.md: the OS in the Tailscale table (§1) and the "Last verified" line. Tick the to-do in §9.
- [ ] `sudo apt autoremove --purge`, after you've booted the new kernel at least once.
- [ ] After a week with no problems, delete `~/upgrade-2604/` on the server. Keep the copy on the PC until the new drive is set up.

---

## If something goes wrong

| Problem | What to do |
|---|---|
| The upgrade stops with an error partway | Don't reboot. Run `sudo dpkg --configure -a`, then `sudo apt -f install`, then `sudo apt full-upgrade`. Logs are in `/var/log/dist-upgrade/`. |
| It won't boot | At the GRUB menu (hold **Shift** or tap **Esc**), choose *Advanced options*, then the previous kernel. Once booted, fix forward with `sudo apt full-upgrade`. |
| No network after boot | From the console: `nmcli dev status`, `sudo systemctl restart NetworkManager`, then `sudo /etc/NetworkManager/dispatcher.d/50-policy-routing enp2s0 up`. |
| LAN SSH dies when the exit node is on | `sudo tailscale set --exit-node-allow-lan-access=true` (README §6). |
| A Docker container won't start | `docker logs <name>`. If the data is the problem, stop the stack and restore from `docker-dirs.tgz` / `docker-volumes.tgz`. |
| Minecraft won't start | `tmux attach -t minecraft` and read the error. Check `java -version`. If OpenJDK 25 was removed: `sudo apt install openjdk-25-jre-headless`. |
| Badly broken | Do a clean install of 26.04, then restore `/etc` pieces from `etc.tgz` (not the whole of `/etc`), Docker data from the tarballs, Minecraft from restic, and re-run each `install.sh` in `~/Desktop/Claud`. README.md is the rebuild guide. |
