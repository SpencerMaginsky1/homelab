#!/usr/bin/env bash
# NAS on the 8TB drive, one account (Spencer) for now: folders, the Samba "Files" share, then the
# full-server backup. Immich itself is started afterwards without sudo (README 3.19).
# Run: sudo bash ~/Desktop/Claude/nas/setup.sh   (safe to re-run)
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "run with sudo"; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
M=/mnt/storage
mountpoint -q "$M" || { echo "$M is not mounted"; exit 1; }

echo "== folders on $M"
install -d -o root    -g root    -m 700 "$M/photos"          # Immich's library (its containers run as root)
install -d -o root    -g root    -m 755 "$M/files"
install -d -o spencer -g spencer -m 755 "$M/files/spencer"   # Samba share "Files"
install -d -o spencer -g spencer -m 755 "$M/media"           # Plex movies later (to-do)
install -d -o root    -g root    -m 700 "$M/backups"         # server + Minecraft backups
ls -la "$M"

echo "== Samba: add the Files share"
bash "$HERE/../samba/install.sh" | grep -E '^== (smbd|shares)' -A3 || true

echo "== full-server backup (first run + test restore)"
bash "$HERE/../backup/install.sh"

echo
echo "Done. Next: tell Claude, which starts Immich (no sudo needed)."
echo "Files on the PC (PowerShell):  net use F: \\\\192.168.1.179\\Files /user:spencer /persistent:yes"
