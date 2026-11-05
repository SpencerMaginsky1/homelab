#!/usr/bin/env python3
"""Lets the dashboard type commands into the Minecraft console (README 3.14).

Listens on a Unix socket that only the dashboard container can reach (group adm, mode 0660) and does
exactly one thing: `tmux send-keys -t minecraft -l <command>` + Enter. One JSON line in, one out.
Runs as spencer from a systemd user service, so the container never gets tmux or a shell.

Refuses unless Java is in the tmux pane's foreground job: if the server is stopped, the pane is a
shell prompt and a "command" would run as a shell command.
"""
import json
import os
import re
import socket
import subprocess

SOCK = os.environ.get("MC_CONSOLE_SOCK", "/home/spencer/Desktop/docker/dashboard/run/mc-console.sock")
SESSION = os.environ.get("MC_TMUX_SESSION", "minecraft")
ADM_GID = 4
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=5, check=False)


def java_in_foreground(tty):
    """True if a java process is in the terminal's foreground job, i.e. it gets what we type.

    Not tmux's #{pane_current_command}: start.sh runs java as a child (no exec), so tmux names
    the foreground job after the script ("sh") even while the server is up.
    """
    if not tty.startswith("/dev/"):
        return False
    ps = subprocess.run(["ps", "-t", tty[5:], "-o", "pgid=,tpgid=,comm="],
                        capture_output=True, text=True, timeout=5, check=False)
    for line in ps.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0] == parts[1] and parts[2] == "java":
            return True
    return False


def handle(raw):
    try:
        cmd = str(json.loads(raw).get("cmd", ""))
    except (ValueError, AttributeError):
        return {"ok": False, "error": "Bad request."}
    cmd = cmd.strip().lstrip("/")
    if not cmd or len(cmd) > 256 or CONTROL.search(cmd):
        return {"ok": False, "error": "A command must be one line of 1 to 256 characters."}
    pane = tmux("display-message", "-p", "-t", SESSION, "#{pane_tty}")
    if pane.returncode:
        return {"ok": False, "error": "The Minecraft tmux session isn't running."}
    if not java_in_foreground(pane.stdout.strip()):
        return {"ok": False, "error": "The Minecraft server isn't running in its tmux session, so nothing was sent."}
    r = tmux("send-keys", "-t", SESSION, "-l", cmd)
    if r.returncode == 0:
        r = tmux("send-keys", "-t", SESSION, "Enter")
    if r.returncode:
        return {"ok": False, "error": r.stderr.strip() or "tmux failed."}
    print(f"sent: {cmd}", flush=True)
    return {"ok": True}


def main():
    os.makedirs(os.path.dirname(SOCK), exist_ok=True)
    try:
        os.unlink(SOCK)
    except FileNotFoundError:
        pass
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(SOCK)
    os.chown(SOCK, -1, ADM_GID)  # the dashboard container runs with the adm group
    os.chmod(SOCK, 0o660)
    srv.listen(4)
    print(f"listening on {SOCK}", flush=True)
    while True:
        conn, _ = srv.accept()
        with conn:
            conn.settimeout(5)
            try:
                data = b""
                while not data.endswith(b"\n") and len(data) < 4096:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                conn.sendall((json.dumps(handle(data.decode("utf-8", "replace"))) + "\n").encode())
            except (OSError, subprocess.TimeoutExpired) as e:
                print(f"error: {e}", flush=True)


if __name__ == "__main__":
    main()
