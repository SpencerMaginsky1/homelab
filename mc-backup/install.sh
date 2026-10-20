#!/usr/bin/env bash
# Install mc-backup: restic, a random repository password, the repository, the 03:30 timer,
# then take the first backup. Run: sudo bash install.sh   (safe to re-run)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
command -v restic >/dev/null || { apt-get update -qq && apt-get install -y -qq restic; }
if [[ ! -s /etc/mc-backup.pass ]]; then
  umask 077; head -c 32 /dev/urandom | base64 > /etc/mc-backup.pass; chmod 600 /etc/mc-backup.pass
  echo "Created /etc/mc-backup.pass - KEEP A COPY of it somewhere else (password manager)."
fi
install -d -o root -g root -m 700 /var/backups/minecraft-restic /var/lib/mc-backup
export RESTIC_REPOSITORY=/var/backups/minecraft-restic RESTIC_PASSWORD_FILE=/etc/mc-backup.pass
restic cat config >/dev/null 2>&1 || restic init
install -o root -g root -m 755 mc-backup /usr/local/bin/mc-backup
install -o root -g root -m 644 mc-backup.service mc-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mc-backup.timer
bash ../healthcheck/install.sh >/dev/null            # daily report: backup-age check
echo "== first backup (live, ~30 s, players unaffected):"
/usr/local/bin/mc-backup backup
/usr/local/bin/mc-backup list
systemctl list-timers mc-backup.timer --no-pager || true
