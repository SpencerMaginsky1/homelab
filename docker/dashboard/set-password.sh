#!/usr/bin/env bash
# Set (or change) the dashboard lock-screen password. README 3.14.
# Asks for the password twice, stores only a salted scrypt hash as DASHBOARD_PASSWORD_HASH in .env,
# then rebuilds and recreates the dashboard container so it picks the new hash (and any code changes) up. Everyone gets locked out and
# has to unlock again with the new password.
set -euo pipefail
cd "$(dirname "$0")"

read -rsp "New dashboard password: " pw1; echo
read -rsp "Type it again: " pw2; echo
if [[ "$pw1" != "$pw2" ]]; then echo "They don't match. Nothing changed."; exit 1; fi
if (( ${#pw1} < 6 )); then echo "Use at least 6 characters. Nothing changed."; exit 1; fi

# The password goes to python on stdin, never on a command line where `ps` could show it.
hash=$(printf '%s' "$pw1" | python3 -c '
import hashlib, os, sys
pw = sys.stdin.buffer.read()
salt = os.urandom(16)
n, r, p = 2**15, 8, 1
h = hashlib.scrypt(pw, salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)
print(f"scrypt:{n}:{r}:{p}:{salt.hex()}:{h.hex()}")
')
unset pw1 pw2

touch .env && chmod 600 .env
grep -v '^DASHBOARD_PASSWORD_HASH=' .env > .env.tmp || true
echo "DASHBOARD_PASSWORD_HASH=$hash" >> .env.tmp
chmod 600 .env.tmp && mv .env.tmp .env
echo "Saved. Restarting the dashboard..."
docker compose up -d --build --force-recreate dashboard
echo "Done. Open http://192.168.1.179:7576 and unlock with the new password."
