#!/usr/bin/env python3
"""Gives the dashboard's Terminal page a real shell on Spencer-Server (README 3.14).

Listens on a Unix socket that only the dashboard container can reach (group adm, mode 0660). The
container has already checked the dashboard lock and the terminal password before it connects.
Runs as spencer from a systemd user service, so the container itself never gets a shell.

Every connection starts with one JSON line:
  {"op": "status"}                       -> one JSON line back: {"ok": true, "session": <tmux session exists>}
  {"op": "attach", "cols": C, "rows": R} -> "ok\\n", then a live terminal:
      bridge -> container: raw terminal output bytes
      container -> bridge: frames of 1 type byte + 4-byte big-endian length + payload
          b"d" keystrokes/paste for the terminal     b"r" resize: cols, rows as two big-endian uint16
The terminal is `tmux new-session -A -s dashboard` (starting in ~/Desktop/Claude), so it keeps
running when the page closes and the next attach (or `tmux attach -t dashboard` over SSH) picks it up.
"""
import fcntl
import json
import os
import pty
import select
import signal
import socket
import struct
import subprocess
import termios
import threading

SOCK = os.environ.get("TERM_BRIDGE_SOCK", "/home/spencer/Desktop/docker/dashboard/run/term.sock")
SESSION = os.environ.get("TERM_TMUX_SESSION", "dashboard")
START_DIR = os.path.expanduser(os.environ.get("TERM_START_DIR", "~/Desktop/Claude"))
ADM_GID = 4
MAX_CLIENTS = 4
_clients = threading.Semaphore(MAX_CLIENTS)


def session_exists():
    r = subprocess.run(["tmux", "has-session", "-t", f"={SESSION}"], capture_output=True, timeout=5, check=False)
    return r.returncode == 0


def set_size(fd, cols, rows):
    cols, rows = max(10, min(int(cols), 500)), max(4, min(int(rows), 200))
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError
        buf += chunk
    return buf


def attach(conn, cols, rows):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TMUX", "TERM_BRIDGE", "INVOCATION_ID", "JOURNAL_STREAM"))}
    env.update(TERM="xterm-256color", COLORTERM="truecolor", LANG=env.get("LANG", "C.UTF-8"), SHELL="/bin/bash")
    pid, fd = pty.fork()
    if pid == 0:   # child: becomes the tmux client in the new terminal
        os.chdir(START_DIR if os.path.isdir(START_DIR) else os.path.expanduser("~"))
        os.execvpe("tmux", ["tmux", "new-session", "-A", "-s", SESSION, "-c", os.getcwd()], env)
    set_size(fd, cols, rows)
    os.set_blocking(fd, False)
    print(f"attach (pid {pid}, {cols}x{rows})", flush=True)
    inbuf = b""
    try:
        while True:
            r, _, _ = select.select([conn, fd], [], [], 30)
            if fd in r:
                try:
                    out = os.read(fd, 65536)
                except BlockingIOError:
                    out = None
                except OSError:   # the tmux client exited (session ended, or `exit` in the last window)
                    break
                if out == b"":
                    break
                if out:
                    conn.sendall(out)
            if conn in r:
                chunk = conn.recv(65536)
                if not chunk:   # the page closed: detach; the tmux session keeps running
                    break
                inbuf += chunk
                while len(inbuf) >= 5:
                    kind, n = inbuf[:1], struct.unpack(">I", inbuf[1:5])[0]
                    if n > 1 << 20:
                        raise ValueError("frame too big")
                    if len(inbuf) < 5 + n:
                        break
                    payload, inbuf = inbuf[5:5 + n], inbuf[5 + n:]
                    if kind == b"d":
                        os.set_blocking(fd, True)
                        os.write(fd, payload)
                        os.set_blocking(fd, False)
                    elif kind == b"r" and n == 4:
                        set_size(fd, *struct.unpack(">HH", payload))
    finally:
        try:
            os.kill(pid, signal.SIGHUP)   # detaches the tmux client only
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
        os.close(fd)
        print(f"detach (pid {pid})", flush=True)


def serve(conn):
    with conn:
        try:
            conn.settimeout(5)
            line = b""
            while not line.endswith(b"\n") and len(line) < 4096:
                chunk = conn.recv(1)
                if not chunk:
                    return
                line += chunk
            req = json.loads(line)
            if req.get("op") == "status":
                conn.sendall((json.dumps({"ok": True, "session": session_exists()}) + "\n").encode())
                return
            if req.get("op") != "attach":
                conn.sendall(b'{"ok": false, "error": "Bad request."}\n')
                return
            if not _clients.acquire(blocking=False):
                conn.sendall(b'{"ok": false, "error": "Too many open terminals."}\n')
                return
            try:
                conn.settimeout(None)
                conn.sendall(b"ok\n")
                attach(conn, req.get("cols", 80), req.get("rows", 24))
            finally:
                _clients.release()
        except (OSError, ValueError, EOFError, subprocess.TimeoutExpired) as e:
            print(f"error: {e!r}", flush=True)


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
    srv.listen(8)
    print(f"listening on {SOCK}", flush=True)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=serve, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
