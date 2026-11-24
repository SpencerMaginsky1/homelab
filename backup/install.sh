#!/usr/bin/env bash
# Install homelab-backup: a random repository password, the repository on /mnt/storage, the 05:00 timer,
# the health check update, then the first backup and a test restore. Run: sudo bash install.sh  (safe to re-run)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
cd "$(dirname "$0")"
mountpoint -q /mnt/storage || { echo "/mnt/storage is not mounted"; exit 1; }
command -v restic >/dev/null || apt-get install -y -qq restic
command -v jq >/dev/null || apt-get install -y -qq jq

if [[ ! -s /etc/homelab-backup.pass ]]; then
  ( umask 077; head -c 32 /dev/urandom | base64 > /etc/homelab-backup.pass ); chmod 600 /etc/homelab-backup.pass
  echo "Created /etc/homelab-backup.pass - KEEP A COPY of it in your password manager (sudo cat /etc/homelab-backup.pass)."
fi
install -d -o root -g root -m 700 /mnt/storage/backups /mnt/storage/backups/server /var/lib/homelab-backup
RESTIC_REPOSITORY=/mnt/storage/backups/server RESTIC_PASSWORD_FILE=/etc/homelab-backup.pass \
  bash -c 'restic cat config >/dev/null 2>&1 || restic init'

install -o root -g root -m 755 homelab-backup /usr/local/bin/homelab-backup
install -o root -g root -m 600 homelab-backup.conf /etc/homelab-backup.conf
install -o root -g root -m 644 homelab-backup.service homelab-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now homelab-backup.timer
bash ../healthcheck/install.sh >/dev/null            # 08:00 report: backup age, drive mounted/SMART/usage

echo "== first backup (a few minutes; later runs take seconds):"
/usr/local/bin/homelab-backup backup
/usr/local/bin/homelab-backup list
/usr/local/bin/homelab-backup stats

echo "== test restore of one folder and one database (into /var/tmp, live files untouched):"
t=/var/tmp/homelab-restore-test
rm -rf "$t"
/usr/local/bin/homelab-backup restore latest /home/spencer/Desktop/Claude/backup "$t"
diff -rq /home/spencer/Desktop/Claude/backup "$t/home/spencer/Desktop/Claude/backup" && echo "folder restore: identical"
/usr/local/bin/homelab-backup restore latest /var/lib/homelab-backup/staging/db "$t"
python3 -I -c 'import sqlite3,sys; print("kuma.db restore:", sqlite3.connect(sys.argv[1]).execute("pragma integrity_check").fetchone()[0])' "$t/var/lib/homelab-backup/staging/db/kuma.db"
ls -la "$t/var/lib/homelab-backup/staging/db"
rm -rf "$t"
systemctl list-timers homelab-backup.timer --no-pager || true
