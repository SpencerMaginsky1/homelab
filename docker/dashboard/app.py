"""Homelab dashboard for Spencer-Server (README 3.14).

Reads everything read-only and needs no passwords:
  Beszel       its SQLite database: servers, history, per-container CPU/RAM
  Uptime Kuma  its SQLite database: monitors, every check, uptime rollups, outages
  Docker       a read-only socket proxy: state, health, settings, logs, rollback images
  journal      /var/log/journal via journalctl: health reports, updater, backups, watchdog
  Minecraft    a server-list ping to HOST_IP:MC_PORT
  weather      Open-Meteo (no key)
Serves:
  /                         the page (index.html)
  /api/summary              everything on the main page
  /api/server/<slug>        /api/monitor/<id>        /api/container/<slug>     (?range=1h|12h|24h|7d)
  /api/activity             the last 30 days of events
  /api/minecraft            server status, settings, players, backups
  /api/console/log          the Minecraft log from a byte position (needs the console password)
  POST /api/console/login | logout | command   (command goes to the console bridge on the host)
  /ping                     200 while the web server is up (Docker healthcheck)
"""
import hashlib
import hmac
import json
import secrets
import os
import re
import socket
import sqlite3
import struct
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "7576"))
BESZEL_DB = os.environ.get("BESZEL_DB", "/data/beszel/data.db")
KUMA_DB = os.environ.get("KUMA_DB", "/data/kuma/kuma.db")
DOCKER_URL = os.environ.get("DOCKER_URL", "http://dashboard-docker-proxy:2375").rstrip("/")
JOURNAL_DIR = os.environ.get("JOURNAL_DIR", "/var/log/journal")
HOST_IP = os.environ.get("HOST_IP", "192.168.1.179")
MC_PORT = int(os.environ.get("MC_PORT", "25565"))
MC_ADDRESS = os.environ.get("MC_ADDRESS", "example.duckdns.org")
WEATHER_LAT = os.environ.get("WEATHER_LAT", "40.71427")
WEATHER_LON = os.environ.get("WEATHER_LON", "-74.00597")
WEATHER_NAME = os.environ.get("WEATHER_NAME", "New York")
MC_DIR = os.environ.get("MC_DIR", "/data/minecraft")
MC_SOCK = os.environ.get("MC_SOCK", "/run/mc-console/mc-console.sock")
CONSOLE_PASSWORD = os.environ.get("CONSOLE_PASSWORD", "")
SESSION_DAYS = 30
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.environ.get("CONFIG", os.path.join(HERE, "config.json"))

# range -> (seconds shown, Beszel record type)
RANGES = {"1h": (3600, "1m"), "12h": (12 * 3600, "10m"), "24h": (24 * 3600, "20m"), "7d": (7 * 86400, "120m")}
STACKS = {"docker": "Dawarich", "homarr": "Homarr", "uptime-kuma": "Monitoring", "beszel": "Monitoring",
          "ships": "Ship Tracker", "dashboard": "Dashboard"}
STACK_ORDER = ["Dawarich", "Homarr", "Monitoring", "Ship Tracker", "Dashboard"]
JOURNAL_TAGS = ["homelab-healthcheck", "homelab-updater", "homelab-watchdog", "mc-backup"]
ACTIVITY_DAYS = 30


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


_cache, _cache_lock = {}, threading.Lock()


def cached(key, ttl, fn):
    """Memoize fn() for ttl seconds. Errors aren't cached, so a broken source is retried next time."""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def utc_ms(s):
    """'2026-11-05 04:39:57.380Z', '2026-11-05 04:40:18.053' or Docker's RFC 3339 (all UTC) -> epoch ms."""
    if not s or s.startswith("0001-"):
        return None
    s = s.strip().replace("T", " ").rstrip("Z")
    s = re.sub(r"[+-]00:00$", "", s)
    base, _, frac = s.partition(".")
    dt = datetime.strptime(base[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000) + int((frac + "000")[:3])


def since_utc(seconds):
    """UTC 'YYYY-MM-DD HH:MM:SS' for now - seconds; sorts correctly against Beszel's and Kuma's timestamps."""
    return datetime.fromtimestamp(time.time() - seconds, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def db(path):
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def load_config():
    def load():
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    return cached("config", 30, load)


# ---------------------------------------------------------------- Beszel

TEMP_NAMES = {"coretemp_package_id_0": "CPU package", "cpu_thermal": "CPU", "acpitz": "Board"}


def temp_keys(t):
    """Up to two sensors to show: the CPU first, then the board."""
    if not t:
        return []
    keys = list(t)
    cpu = (next((k for k in keys if "package" in k), None) or next((k for k in keys if "cpu" in k), None)
           or max(keys, key=lambda k: t[k]))
    return [cpu] + (["acpitz"] if "acpitz" in t and cpu != "acpitz" else [])


def temp_name(k):
    return TEMP_NAMES.get(k, k.replace("_", " "))


def cpu_short(model):
    m = re.sub(r"\((R|TM)\)|CPU|@.*$", "", model or "").split()
    return " ".join(m)


def bandwidth(st):
    """[up, down] bytes/s. Newer agents send 'b' in bytes, older ones 'ns'/'nr' in MB/s."""
    if "b" in st:
        return st["b"][0], st["b"][1]
    return st.get("ns", 0) * 1048576, st.get("nr", 0) * 1048576


def disk_io(st):
    if "dio" in st:
        return st["dio"][0], st["dio"][1]
    return st.get("dr", 0) * 1048576, st.get("dw", 0) * 1048576


def beszel_systems():
    def load():
        with closing(db(BESZEL_DB)) as c:
            details = {r["system"]: dict(r) for r in c.execute("select * from system_details")}
            hour = since_utc(3600) + ".000Z"
            out = []
            for r in c.execute("select id, name, status, info, updated from systems order by name"):
                info = json.loads(r["info"] or "{}")
                last = c.execute("select stats from system_stats where system=? and type='1m' order by created desc limit 1",
                                 (r["id"],)).fetchone()
                st = json.loads(last["stats"]) if last else {}
                spark = [json.loads(x["stats"]).get("cpu", 0) for x in c.execute(
                    "select stats from system_stats where system=? and type='1m' and created>=? order by created", (r["id"], hour))]
                d = details.get(r["id"], {})
                t = st.get("t") or {}
                tk = temp_keys(t)
                out.append({
                    "id": slug(r["name"]), "bid": r["id"], "name": r["name"], "status": r["status"],
                    "updated": utc_ms(r["updated"]), "uptime": info.get("u"),
                    "cpu": st.get("cpu", info.get("cpu")), "ram": [st.get("mu"), st.get("m")], "cache": st.get("mb"),
                    "swap": [st.get("su"), st.get("s")], "disk": [st.get("du"), st.get("d")],
                    "temp": t.get(tk[0]) if tk else None, "temp_name": temp_name(tk[0]) if tk else None,
                    "load": st.get("la") or info.get("la"),
                    "nics": [{"name": k, "up": v[0], "down": v[1], "total_up": v[2] if len(v) > 2 else None,
                              "total_down": v[3] if len(v) > 3 else None} for k, v in (st.get("ni") or {}).items()],
                    "cpu_model": cpu_short(d.get("cpu")), "cores": d.get("cores"), "threads": d.get("threads"),
                    "kernel": d.get("kernel"), "os": d.get("os_name"), "arch": d.get("arch"), "agent": info.get("v"),
                    "spark": spark,
                })
            return out
    return cached("systems", 10, load)


def beszel_fresh():
    """True if the Beszel hub has written stats in the last 3 minutes."""
    with closing(db(BESZEL_DB)) as c:
        r = c.execute("select max(created) as m from system_stats where type='1m'").fetchone()
    return bool(r["m"]) and time.time() * 1000 - utc_ms(r["m"]) < 180_000


def beszel_history(bid, rng):
    span, typ = RANGES[rng]
    with closing(db(BESZEL_DB)) as c:
        rows = [(utc_ms(r["created"]), json.loads(r["stats"])) for r in c.execute(
            "select created, stats from system_stats where system=? and type=? and created>=? order by created",
            (bid, typ, since_utc(span)))]
    tk = temp_keys(rows[-1][1].get("t")) if rows else []
    h = {"t": [], "cpu": [], "mem_used": [], "mem_cache": [], "net_up": [], "net_down": [],
         "disk_read": [], "disk_write": [], "load1": [], "load15": [],
         "temps": [{"name": temp_name(k), "values": []} for k in tk]}
    for t, st in rows:
        h["t"].append(t)
        h["cpu"].append(st.get("cpu"))
        h["mem_used"].append(st.get("mu"))
        h["mem_cache"].append(st.get("mb"))
        up, down = bandwidth(st)
        h["net_up"].append(up)
        h["net_down"].append(down)
        rd, wr = disk_io(st)
        h["disk_read"].append(rd)
        h["disk_write"].append(wr)
        la = st.get("la") or [None, None, None]
        h["load1"].append(la[0])
        h["load15"].append(la[2])
        for k, s in zip(tk, h["temps"]):
            s["values"].append((st.get("t") or {}).get(k))
    return h


def beszel_containers():
    with closing(db(BESZEL_DB)) as c:
        return {r["name"]: dict(r) for r in c.execute("select name, cpu, memory, system from containers")}


def beszel_container_history(bid, name, rng):
    span, typ = RANGES[rng]
    t, cpu, mem = [], [], []
    with closing(db(BESZEL_DB)) as c:
        for r in c.execute("select created, stats from container_stats where system=? and type=? and created>=? order by created",
                           (bid, typ, since_utc(span))):
            hit = next((x for x in json.loads(r["stats"]) if x.get("n") == name), None)
            if hit:
                t.append(utc_ms(r["created"]))
                cpu.append(hit.get("c"))
                mem.append(hit.get("m"))
    return {"t": t, "cpu": cpu, "mem": mem}


# ---------------------------------------------------------------- Uptime Kuma

KUMA_KIND = {"http": "HTTP", "keyword": "HTTP keyword", "json-query": "HTTP JSON", "ping": "Ping", "port": "TCP port",
             "gamedig": "Game server", "dns": "DNS", "docker": "Docker container", "push": "Push"}


def kuma_target(m):
    if m["type"] in ("http", "keyword", "json-query"):
        s = m["url"]
        if m["keyword"]:
            s += f' (must contain "{m["keyword"]}")'
        return s
    if m["port"]:
        return f'{m["hostname"]}:{m["port"]}'
    return m["hostname"] or ""


def uptime_pct(up, down):
    return round(up / (up + down) * 100, 2) if up + down else None


def kuma_monitors():
    def load():
        day = int(time.time()) - 86400
        out = []
        with closing(db(KUMA_DB)) as c:
            for m in c.execute("select id, name, type, url, hostname, port, interval, keyword from monitor where active=1 order by name"):
                beats = c.execute("select status, ping, time from heartbeat where monitor_id=? order by time desc limit 30",
                                  (m["id"],)).fetchall()[::-1]
                up, down = c.execute("select coalesce(sum(up),0), coalesce(sum(down),0) from stat_minutely where monitor_id=? and timestamp>=?",
                                     (m["id"], day)).fetchone()
                out.append({
                    "id": m["id"], "name": m["name"], "kind": KUMA_KIND.get(m["type"], m["type"]), "target": kuma_target(m),
                    "interval": m["interval"], "status": beats[-1]["status"] if beats else None,
                    "last": utc_ms(beats[-1]["time"]) if beats else None, "ping": beats[-1]["ping"] if beats else None,
                    "beats": [b["status"] for b in beats], "uptime24": uptime_pct(up, down),
                })
        return out
    return cached("monitors", 10, load)


def kuma_alive():
    with closing(db(KUMA_DB)) as c:
        r = c.execute("select max(time) as m from heartbeat").fetchone()
    return bool(r["m"]) and time.time() * 1000 - utc_ms(r["m"]) < 180_000


def outage_reason(msg):
    if not msg:
        return "Check failed"
    if "packet loss" in msg:
        return "No ping reply"
    if "keyword is not in" in msg:
        return "Expected text not found"
    code = re.search(r"status code (\d+)", msg)
    if code:
        return f"HTTP {code.group(1)}"
    if "timeout" in msg.lower():
        return "Timed out"
    if "EPROTO" in msg or "wrong version number" in msg:
        return "TLS error (HTTPS check on an HTTP port)"
    return msg.strip().splitlines()[0][:140]


def kuma_outages(c, mid, interval, days=30):
    """Runs of failed checks. 'down' = Kuma alerted; 'retrying' = failed checks that recovered before an alert.

    Kuma keeps every check for about two days and only the alert (important) checks after that, so recent runs
    come from all checks and older ones from down -> up alert pairs.
    """
    since, gap, step = since_utc(days * 86400), max(600_000, interval * 5000), interval * 1000
    runs, cur, prev = [], None, None
    for r in c.execute("select status, time, msg from heartbeat where monitor_id=? and time>=? order by time", (mid, since)):
        t = utc_ms(r["time"])
        if cur and prev and t - prev > gap:  # checks missing here; don't let a run stretch across the hole
            cur["end"] = prev + step
            runs.append(cur)
            cur = None
        prev = t
        if r["status"] in (0, 2):
            if cur is None:
                cur = {"start": t, "end": None, "down": False, "checks": 0, "msg": None, "msg_down": False}
            cur["checks"] += 1
            cur["down"] = cur["down"] or r["status"] == 0
            if r["msg"] and (not cur["msg"] or r["status"] == 0 and not cur["msg_down"]):
                cur["msg"], cur["msg_down"] = r["msg"], r["status"] == 0
        elif r["status"] == 1 and cur:
            cur["end"] = t
            runs.append(cur)
            cur = None
    if cur:
        runs.append(cur)
    opened = None
    for r in c.execute("select status, time, msg from heartbeat where monitor_id=? and important=1 and time>=? order by time", (mid, since)):
        t = utc_ms(r["time"])
        if r["status"] == 0:
            opened = (t, r["msg"])
        elif r["status"] == 1 and opened:
            if not any(abs(o["start"] - opened[0]) < 600_000 or o["start"] <= opened[0] <= (o["end"] or t) for o in runs):
                runs.append({"start": opened[0], "end": t, "down": True, "checks": None, "msg": opened[1]})
            opened = None
    runs.sort(key=lambda o: o["start"], reverse=True)
    return [{"start": o["start"], "end": o["end"], "type": "down" if o["down"] else "retrying", "checks": o["checks"],
             "reason": outage_reason(o["msg"])} for o in runs]


def kuma_detail(mid, rng):
    span = RANGES[rng][0]
    now = int(time.time())
    with closing(db(KUMA_DB)) as c:
        m = c.execute("select id, name, type, url, hostname, port, interval, keyword, active from monitor where id=?", (mid,)).fetchone()
        if not m:
            return None
        beats = [dict(b) for b in c.execute("select status, ping, time, msg from heartbeat where monitor_id=? order by time desc limit 100",
                                             (mid,)).fetchall()[::-1]]

        def up_down(table, since):
            return c.execute(f"select coalesce(sum(up),0), coalesce(sum(down),0) from {table} where monitor_id=? and timestamp>=?",
                             (mid, since)).fetchone()

        t, ping, down = [], [], []
        if rng == "1h":
            for b in c.execute("select status, ping, time from heartbeat where monitor_id=? and time>=? order by time", (mid, since_utc(span))):
                t.append(utc_ms(b["time"]))
                ping.append(b["ping"] if b["status"] == 1 else None)
                down.append(0 if b["status"] == 1 else 1)
        else:
            table, bucket = ("stat_hourly", 3600) if rng == "7d" else ("stat_minutely", 600 if rng == "12h" else 1200)
            agg = {}
            for r in c.execute(f"select timestamp, ping, up, down from {table} where monitor_id=? and timestamp>=? order by timestamp",
                               (mid, now - span)):
                k = r["timestamp"] // bucket * bucket
                a = agg.setdefault(k, [0.0, 0, 0])
                a[0] += (r["ping"] or 0) * r["up"]
                a[1] += r["up"]
                a[2] += r["down"]
            for k in sorted(agg):
                s, u, d = agg[k]
                t.append(k * 1000)
                ping.append(round(s / u, 1) if u else None)
                down.append(d)
        pu, pd = c.execute("select coalesce(sum(ping*up),0), coalesce(sum(up),0) from stat_minutely where monitor_id=? and timestamp>=?",
                           (mid, now - 86400)).fetchone()
        res = {
            "id": m["id"], "name": m["name"], "kind": KUMA_KIND.get(m["type"], m["type"]), "target": kuma_target(m),
            "interval": m["interval"], "active": bool(m["active"]),
            "status": beats[-1]["status"] if beats else None, "ping": beats[-1]["ping"] if beats else None,
            "last": utc_ms(beats[-1]["time"]) if beats else None, "avg24": round(pu / pd, 1) if pd else None,
            "uptime24": uptime_pct(*up_down("stat_minutely", now - 86400)),
            "uptime7": uptime_pct(*up_down("stat_hourly", now - 7 * 86400)),
            "uptime30": uptime_pct(*up_down("stat_daily", now - 30 * 86400)),
            "beats": [{"status": b["status"], "ping": b["ping"], "t": utc_ms(b["time"])} for b in beats],
            "history": {"t": t, "ping": ping, "down": down},
            "outages": kuma_outages(c, mid, m["interval"] or 60),
        }
    return res


# ---------------------------------------------------------------- Docker

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
SECRET = re.compile(r"((?:api[_-]?key|token|password|passwd|secret|authorization)[\"']?\s*[=:]\s*[\"']?)([^\s&\"',;]+)", re.I)


def docker(path, raw=False):
    with urllib.request.urlopen(DOCKER_URL + path, timeout=5) as r:
        data = r.read()
    return data if raw else json.loads(data)


def inspect(cid):
    return cached("inspect:" + cid, 30, lambda: docker(f"/containers/{cid}/json"))


def health_of(status, state):
    if "(healthy)" in status:
        return "healthy"
    if "(unhealthy)" in status:
        return "unhealthy"
    if "health: starting" in status:
        return "starting"
    return "running" if state == "running" else state


def containers():
    def load():
        systems = {s["bid"]: s["id"] for s in beszel_systems()}
        bz = beszel_containers()
        out = []
        for c in docker("/containers/json?all=1"):
            name = c["Names"][0].lstrip("/")
            ins = inspect(c["Id"])
            project = (c.get("Labels") or {}).get("com.docker.compose.project", "")
            b = bz.get(name) or {}
            out.append({
                "name": name, "slug": slug(name), "id": c["Id"][:12], "image": ins["Config"]["Image"], "state": c["State"],
                "health": health_of(c.get("Status", ""), c["State"]), "status": c.get("Status", ""),
                "project": project, "stack": STACKS.get(project, project.replace("-", " ").title() or "Other"),
                "host": systems.get(b.get("system"), "spencer-server"), "bid": b.get("system"),
                "cpu": b.get("cpu"), "mem": b.get("memory"),
                "limit": round(ins["HostConfig"]["Memory"] / 1048576) if ins["HostConfig"].get("Memory") else None,
                "started": utc_ms(ins["State"].get("StartedAt")) if c["State"] == "running" else None,
            })
        order = {s: i for i, s in enumerate(STACK_ORDER)}
        out.sort(key=lambda x: (order.get(x["stack"], 99), x["stack"], x["name"]))
        return out
    return cached("containers", 10, load)


def rollbacks(name, image):
    repo = image.rpartition(":")[0] if ":" in image.split("/")[-1] else image
    out, svc = [], None
    for im in cached("images", 60, lambda: docker("/images/json")):
        for tag in im.get("RepoTags") or []:
            r, _, tg = tag.rpartition(":")
            if r == "homelab-rollback":
                parts = tg.split(".")
                if len(parts) == 3 and parts[1] == name:
                    svc = parts[0]
                    try:
                        label = datetime.strptime(parts[2], "%Y%m%d-%H%M%S").strftime("%b %-d, %-I:%M %p")
                    except ValueError:
                        label = parts[2]
                    out.append({"label": label, "key": parts[2], "size": im.get("Size")})
            elif r == repo and tg.endswith("-rollback"):
                out.append({"label": f"{tg.removesuffix('-rollback')} (manual tag)", "key": "0", "size": im.get("Size")})
    out.sort(key=lambda x: x["key"], reverse=True)
    return out, svc


def demux(raw):
    """Split Docker's multiplexed log stream (8-byte frame headers) into (stream, bytes) chunks."""
    i, out = 0, []
    while i + 8 <= len(raw):
        size = struct.unpack(">I", raw[i + 4:i + 8])[0]
        out.append(("err" if raw[i] == 2 else "out", raw[i + 8:i + 8 + size]))
        i += 8 + size
    return out


def container_logs(cid, tty):
    raw = docker(f"/containers/{cid}/logs?stdout=1&stderr=1&tail=80&timestamps=1", raw=True)
    chunks = [("out", raw)] if tty else demux(raw)
    lines = []
    for stream, data in chunks:
        for line in data.decode("utf-8", "replace").splitlines():
            ts, _, msg = line.partition(" ")
            try:
                t = utc_ms(ts)
            except ValueError:
                t, msg = None, line
            msg = SECRET.sub(r"\1***", ANSI.sub("", msg)).rstrip()
            if msg:
                lines.append({"t": t, "stream": stream, "msg": msg[:400]})
    lines.sort(key=lambda x: x["t"] or 0)
    return lines[-80:]


def health_cmd(test):
    if not test or test[0] == "NONE":
        return None
    return test[1] if test[0] == "CMD-SHELL" else " ".join(test[1:])


def container_detail(cslug, rng):
    c = next((x for x in containers() if x["slug"] == cslug), None)
    if not c:
        return None
    ins = docker(f"/containers/{c['id']}/json")
    hc, st = ins["Config"].get("Healthcheck") or {}, ins["State"]
    ports = [f'{v[0]["HostPort"]} → {k}' for k, v in (ins["NetworkSettings"].get("Ports") or {}).items() if v]
    mode = ins["HostConfig"].get("NetworkMode", "")
    rb, svc = rollbacks(c["name"], ins["Config"]["Image"])
    hlog = (st.get("Health") or {}).get("Log") or []
    try:
        logs, logs_error = container_logs(c["id"], ins["Config"].get("Tty")), None
    except Exception as e:  # noqa: BLE001 - shown on the page
        logs, logs_error = [], str(e)
    return {
        **c,
        "image_id": ins["Image"].split(":")[-1][:12], "created": utc_ms(ins["Created"]),
        "restart": (ins["HostConfig"].get("RestartPolicy") or {}).get("Name") or "no", "restarts": ins.get("RestartCount", 0),
        "ports": ports, "network_mode": mode, "networks": list((ins["NetworkSettings"].get("Networks") or {}).keys()),
        "mounts": [{"src": m.get("Source") or m.get("Name"), "dst": m["Destination"], "rw": m.get("RW", True)} for m in ins.get("Mounts", [])],
        "check": health_cmd(hc.get("Test")), "check_interval": (hc.get("Interval") or 0) // 1_000_000_000 or None,
        "failing": (st.get("Health") or {}).get("FailingStreak"),
        "health_log": [{"t": utc_ms(h.get("Start")), "exit": h.get("ExitCode"), "output": (h.get("Output") or "").strip()[:200]}
                       for h in hlog[-5:]][::-1],
        "workdir": (ins["Config"].get("Labels") or {}).get("com.docker.compose.project.working_dir"),
        "rollbacks": rb, "rollback_svc": svc,
        "logs": logs, "logs_error": logs_error,
        "history": beszel_container_history(c["bid"], c["name"], rng) if c["bid"] else {"t": [], "cpu": [], "mem": []},
    }


# ---------------------------------------------------------------- Minecraft and weather

def _varint(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n:
            return out


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed")
        buf += chunk
    return buf


def _read_varint(sock):
    n = shift = 0
    while True:
        b = _recv(sock, 1)[0]
        n |= (b & 0x7F) << shift
        shift += 7
        if not b & 0x80:
            return n


def _motd(d):
    if isinstance(d, str):
        return re.sub(r"§.", "", d)
    if isinstance(d, dict):
        return _motd(d.get("text", "")) + "".join(_motd(x) for x in d.get("extra", []))
    return ""


def minecraft():
    def load():
        try:
            with socket.create_connection((HOST_IP, MC_PORT), timeout=3) as s:
                s.settimeout(3)
                host = HOST_IP.encode()
                hs = b"\x00" + _varint(767) + _varint(len(host)) + host + struct.pack(">H", MC_PORT) + _varint(1)
                s.sendall(_varint(len(hs)) + hs + b"\x01\x00")
                _read_varint(s)
                _read_varint(s)
                j = json.loads(_recv(s, _read_varint(s)))
            p = j.get("players") or {}
            return {"online": True, "players": p.get("online", 0), "max": p.get("max", 0),
                    "names": [x.get("name") for x in p.get("sample") or [] if x.get("name")],
                    "version": (j.get("version") or {}).get("name"), "motd": _motd(j.get("description")).strip(),
                    "address": MC_ADDRESS}
        except OSError as e:
            return {"online": False, "error": str(e), "address": MC_ADDRESS}
    return cached("minecraft", 20, load)


WMO = {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog", 51: "Light drizzle",
       53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle", 61: "Light rain", 63: "Rain",
       65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
       77: "Snow grains", 80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
       95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm"}


def weather():
    def load():
        q = urllib.parse.urlencode({"latitude": WEATHER_LAT, "longitude": WEATHER_LON,
                                    "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph"})
        with urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=8) as r:
            cur = json.load(r)["current"]
        return {"temp": round(cur["temperature_2m"]), "text": WMO.get(cur["weather_code"], ""), "wind": round(cur["wind_speed_10m"]),
                "humidity": cur.get("relative_humidity_2m"), "place": WEATHER_NAME}
    return cached("weather", 900, load)


# ---------------------------------------------------------------- activity (journal + Kuma)

def journal(since):
    cmd = ["journalctl", "-D", JOURNAL_DIR, "-o", "json", "--no-pager", "-q", "--since", f"@{int(since)}",
           "--output-fields=MESSAGE,SYSLOG_IDENTIFIER,_PID"]
    for tag in JOURNAL_TAGS:
        cmd += ["-t", tag]
    out = subprocess.run(cmd, capture_output=True, timeout=30, check=False).stdout
    entries = []
    for line in out.splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        msg = j.get("MESSAGE")
        if isinstance(msg, list):
            msg = bytes(msg).decode("utf-8", "replace")
        if msg:
            entries.append({"t": int(j["__REALTIME_TIMESTAMP"]) // 1000, "tag": j.get("SYSLOG_IDENTIFIER"),
                            "pid": j.get("_PID"), "msg": msg.rstrip()})
    return entries


def ev(t, sev, cat, src, title, body="", lines=None, link=None, raw=None):
    """One activity event. The id is stable across reloads, so #event-<id> links keep working."""
    eid = hashlib.sha1(f"{src}|{t}|{title}".encode()).hexdigest()[:10]
    return {"id": eid, "t": t, "sev": sev, "cat": cat, "src": src, "title": title, "body": body,
            "lines": lines or [], "link": link, "raw": raw or []}


def raw_of(*entries):
    return [{"t": e["t"], "text": e["msg"]} for e in entries if e]


TITLE_RE = re.compile(r"^(✅|⚠️?|🚨)\s*(?:[\w.-]+:\s*)?(.*)$")


def health_events(es):
    out = []
    for ti in (e for e in es if TITLE_RE.match(e["msg"])):
        sym, text = TITLE_RE.match(ti["msg"]).groups()
        fails, warns, passed, sec = [], [], [], None
        run = sorted((e for e in es if abs(e["t"] - ti["t"]) <= 120_000 and e["pid"] != ti["pid"]), key=lambda e: e["t"])
        for e in run:
            m = e["msg"]
            if m.startswith("FAILURES"):
                sec = fails
            elif m.startswith("WARNINGS"):
                sec = warns
            elif m.startswith("PASSED:"):
                passed, sec = [p.strip() for p in m[7:].split(";") if p.strip()], None
            elif m.lstrip().startswith("- ") and sec is not None:
                sec.append(m.lstrip()[2:])
            elif not m.startswith(" "):
                sec = None
        sev = {"✅": "ok", "🚨": "bad"}.get(sym, "warn")
        body = "; ".join(fails + warns) if fails or warns else f"All {len(passed)} checks passed." if passed else ""
        lines = [{"sev": "bad", "text": x} for x in fails] + [{"sev": "warn", "text": x} for x in warns] + \
                [{"sev": "ok", "text": x} for x in passed]
        out.append(ev(ti["t"], sev, "report", "healthcheck", f"Health report: {text}", body, lines, None, raw_of(ti, *run)))
    return out


def svc_link(svc):
    names = {c["name"]: c["slug"] for c in containers()}
    for n in (svc, f"{svc}_app"):
        if n in names:
            return f"#container-{names[n]}"
    return None


def updater_events(es):
    out, started = [], {}
    for e in es:
        m, t = e["msg"], e["t"]
        head, _, rest = m.partition(": ")
        items = [x.strip() for x in rest.split(";") if x.strip()]
        if m.startswith("UPDATING "):
            started[m.split()[1]] = e
        elif m.startswith("UPDATED "):
            svc = head[8:]
            out.append(ev(t, "info", "update", "updater", f"Updated {svc}", "; ".join(items[:2]), [{"sev": "ok", "text": x} for x in items],
                          svc_link(svc), raw_of(started.pop(svc, None), e)))
        elif m.startswith("AVAILABLE "):
            svc = head[10:]
            out.append(ev(t, "warn", "waiting", "updater", f"Update waiting for you: {svc}",
                          f"{'; '.join(items)}. Run sudo homelab-updater apply {svc}", None, svc_link(svc), raw_of(e)))
        elif m.startswith("FAILED "):
            svc = head[7:]
            out.append(ev(t, "bad", "problem", "updater", f"Update problem: {svc}", rest, None, svc_link(svc), raw_of(started.get(svc), e)))
        elif m.startswith("ROLLEDBACK "):
            svc = m.split()[1]
            out.append(ev(t, "warn", "update", "updater", f"Rolled back {svc}", m, None, svc_link(svc), raw_of(e)))
        elif m.startswith("pull failed for "):
            svc = m[16:]
            out.append(ev(t, "warn", "update", "updater", f"Couldn't download the {svc} update", "It tries again at the next run.", None, None, raw_of(e)))
    return out


def watchdog_events(es):
    out = []
    for e in es:
        m = e["msg"]
        if m.startswith("FIXED "):
            out.append(ev(e["t"], "warn", "problem", "watchdog", f"Watchdog restarted {m[6:]}", "It was down; restarting it fixed it.", None, None, raw_of(e)))
        elif m.startswith("FAILED "):
            key, _, rest = m[7:].partition(": ")
            out.append(ev(e["t"], "bad", "problem", "watchdog", f"Watchdog couldn't fix {key}", rest, None, None, raw_of(e)))
        elif m.startswith("RECOVERED "):
            out.append(ev(e["t"], "ok", "problem", "watchdog", f"{m[10:]} is back up", "", None, None, raw_of(e)))
    return out


def backup_events(es):
    out, done, extra, run = [], None, [], []
    for e in sorted(es, key=lambda e: e["t"]):
        m = e["msg"]
        # a run starts at "players online" (when it warns players first) or at "backup started"
        if m.startswith("players online:") or m.startswith("backup started") and not (run and run[-1]["msg"].startswith("players online:")):
            run = []
        run.append(e)
        if m.startswith("backup done:"):
            done = m
        elif m.startswith("weekly integrity check OK"):
            extra.append({"sev": "ok", "text": "Weekly integrity check passed"})
        elif m.startswith("OK "):
            snap = re.search(r"snapshot (\w+) saved", done or "")
            n, size = re.search(r"snapshots=(\d+)", m), re.search(r"size=(\S+)", m)
            added = re.search(r"Added to the repository: ([\d.]+ \w+)", done or "")
            body = ", ".join(x for x in [f"Snapshot {snap.group(1)} saved" if snap else "Saved",
                                         f"{n.group(1)} snapshots kept" if n else "", f"{size.group(1)} total" if size else ""] if x)
            lines = extra + ([{"sev": "ok", "text": f"Added {added.group(1)} of changes"}] if added else [])
            out.append(ev(e["t"], "ok", "backup", "mc-backup", "Minecraft backup done", body, lines, "#minecraft", raw_of(*run)))
            done, extra, run = None, [], []
        elif m.startswith("FAILED:"):
            out.append(ev(e["t"], "bad", "problem", "mc-backup", "Minecraft backup failed", m[7:].strip(), None, "#minecraft", raw_of(*run)))
            run = []
        elif m.startswith("RESTORED"):
            out.append(ev(e["t"], "info", "backup", "mc-backup", "Minecraft world restored", m, None, "#minecraft", raw_of(*run)))
        elif m.startswith("warning:"):
            out.append(ev(e["t"], "warn", "backup", "mc-backup", "Backup warning", m[8:].strip(), None, "#minecraft", raw_of(e)))
    return out


def fmt_dur(ms):
    s = max(0, ms // 1000)
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{round(s / 60)} min"
    if s < 172800:
        return f"{s // 3600} h {s % 3600 // 60} min"
    return f"{s // 86400} d {s % 86400 // 3600} h"


def kuma_events(since):
    out, downs = [], {}
    with closing(db(KUMA_DB)) as c:
        names = {r["id"]: r["name"] for r in c.execute("select id, name from monitor")}
        for r in c.execute("select monitor_id, status, time, msg from heartbeat where important=1 and time>=? order by time",
                           (since_utc(time.time() - since),)):
            t, mid = utc_ms(r["time"]), r["monitor_id"]
            name = names.get(mid, f"Monitor {mid}")
            raw = [{"t": t, "text": f"{name}: {'DOWN' if r['status'] == 0 else 'UP'}" + (f" - {r['msg'].strip()}" if r["msg"] else "")}]
            if r["status"] == 0:
                downs[mid] = t
                out.append(ev(t, "bad", "problem", "Uptime Kuma", f"{name} is down", outage_reason(r["msg"]), None, f"#monitor-{mid}", raw))
            elif r["status"] == 1 and mid in downs:
                out.append(ev(t, "ok", "problem", "Uptime Kuma", f"{name} is back up", f"Down for {fmt_dur(t - downs.pop(mid))}", None, f"#monitor-{mid}", raw))
    return out


def activity():
    def load():
        since = time.time() - ACTIVITY_DAYS * 86400
        es = journal(since)
        by = {tag: [e for e in es if e["tag"] == tag] for tag in JOURNAL_TAGS}
        events = (health_events(by["homelab-healthcheck"]) + updater_events(by["homelab-updater"]) +
                  watchdog_events(by["homelab-watchdog"]) + backup_events(by["mc-backup"]) + kuma_events(since))
        events.sort(key=lambda e: e["t"], reverse=True)
        return events
    return cached("activity", 60, load)


def activity_summary(events):
    week = time.time() * 1000 - 7 * 86400_000
    waiting, done = {}, set()
    for e in events:  # newest first: an update applied after the "waiting" notice clears it
        if e["title"].startswith("Updated "):
            done.add(e["title"][8:])
        elif e["cat"] == "waiting":
            svc = e["title"].rsplit(": ", 1)[-1]
            if svc not in done and svc not in waiting:
                waiting[svc] = e
    report = next((e for e in events if e["cat"] == "report"), None)
    return {
        "problems": sum(1 for e in events if e["t"] >= week and e["sev"] == "bad"),
        "updates": sum(1 for e in events if e["t"] >= week and e["title"].startswith("Updated ")),
        "waiting": [{"svc": k, "body": v["body"], "t": v["t"], "link": v["link"]} for k, v in waiting.items()],
        "report": {"title": report["title"], "sev": report["sev"], "t": report["t"], "body": report["body"]} if report else None,
    }


# ---------------------------------------------------------------- Minecraft page and console

MC_PROPS = ["motd", "gamemode", "difficulty", "hardcore", "max-players", "white-list", "enforce-whitelist", "online-mode",
            "pvp", "allow-flight", "view-distance", "simulation-distance", "spawn-protection", "level-name"]
JOIN_RE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] \[[^\]]+\]: (\w{2,16}) (joined|left) the game")


def mc_props():
    out = {}
    with open(os.path.join(MC_DIR, "server.properties"), encoding="utf-8") as f:
        for line in f:
            k, sep, v = line.strip().partition("=")
            if sep and k in MC_PROPS:
                out[k] = v
    return [[k, out[k]] for k in MC_PROPS if k in out]


def mc_names(fname):
    try:
        with open(os.path.join(MC_DIR, fname), encoding="utf-8") as f:
            return sorted((x.get("name") or x.get("ip") or "?") for x in json.load(f))
    except (OSError, ValueError):
        return []


def world_size():
    def load():
        total = 0
        for root, _, files in os.walk(os.path.join(MC_DIR, "world")):
            for name in files:
                try:
                    total += os.lstat(os.path.join(root, name)).st_size
                except OSError:
                    pass
        return total
    return cached("world_size", 600, load)


def todays_players():
    """Join/leave lines from today's log, newest first."""
    out = []
    try:
        with open(os.path.join(MC_DIR, "logs", "latest.log"), encoding="utf-8", errors="replace") as f:
            for line in f:
                m = JOIN_RE.match(line)
                if m:
                    out.append({"time": m.group(1), "name": m.group(2), "event": m.group(3)})
    except OSError:
        pass
    return out[::-1]


def minecraft_detail(authed):
    errors = {}
    mon = next((m for m in section(errors, "kuma", kuma_monitors, []) if m["kind"] == "Game server"), None)
    kd = section(errors, "kuma", lambda: kuma_detail(mon["id"], "24h"), None) if mon else None
    backups = [e for e in section(errors, "activity", activity, []) if e["src"] == "mc-backup"][:7]
    return {
        "status": minecraft(), "props": section(errors, "settings", mc_props, []),
        "ops": mc_names("ops.json"), "whitelist": mc_names("whitelist.json"),
        "banned": len(mc_names("banned-players.json")) + len(mc_names("banned-ips.json")),
        "world_size": section(errors, "world", world_size), "today": todays_players(),
        "monitor": {k: kd[k] for k in ("id", "uptime24", "uptime7", "uptime30", "outages")} if kd else None,
        "backups": backups, "authed": authed, "console_ready": bool(CONSOLE_PASSWORD), "bridge": os.path.exists(MC_SOCK),
        "errors": errors,
    }


def console_log(pos, ino):
    """New complete lines of latest.log after byte pos. pos=None: the last ~64 KB. A new file (restart or
    midnight rotation) changes the inode, so the client starts over."""
    path = os.path.join(MC_DIR, "logs", "latest.log")
    st = os.stat(path)
    reset = pos is None or ino != st.st_ino or pos > st.st_size
    start = max(0, st.st_size - 65536) if pos is None else 0 if reset else pos
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(min(st.st_size - start, 262144))
    cut = data.find(b"\n") + 1 if pos is None and start > 0 else 0
    body = data[cut:]
    end = body.rfind(b"\n") + 1
    return {"pos": start + cut + end, "ino": st.st_ino, "reset": reset,
            "lines": body[:end].decode("utf-8", "replace").splitlines()}


def console_send(cmd):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(8)
            s.connect(MC_SOCK)
            s.sendall((json.dumps({"cmd": cmd}) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        return json.loads(data)
    except (OSError, ValueError):
        return {"ok": False, "error": "The console bridge isn't running on the server. Run: bash ~/Desktop/docker/dashboard/console-bridge/install.sh"}


_sessions, _fails, _auth_lock = {}, {}, threading.Lock()


def login(ip, password):
    now = time.time()
    with _auth_lock:
        _fails[ip] = [t for t in _fails.get(ip, []) if now - t < 300]
        if len(_fails[ip]) >= 5:
            return None, "Too many wrong passwords. Try again in 5 minutes."
    if not CONSOLE_PASSWORD:
        return None, "No console password is set on the server (CONSOLE_PASSWORD in ~/Desktop/docker/dashboard/.env)."
    if not hmac.compare_digest(password.encode(), CONSOLE_PASSWORD.encode()):
        time.sleep(1)
        with _auth_lock:
            _fails[ip].append(now)
        return None, "Wrong password."
    tok = secrets.token_urlsafe(32)
    with _auth_lock:
        _sessions[tok] = now + SESSION_DAYS * 86400
    return tok, None


# ---------------------------------------------------------------- API

def section(errors, name, fn, default=None):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001 - one broken source shouldn't blank the whole page
        log(f"{name}: {e}")
        errors[name] = str(e)
        return default


def summary():
    errors = {}
    cfg = section(errors, "config", load_config, {"apps": [], "shortcuts": []})
    machines = section(errors, "beszel", beszel_systems, [])
    monitors = section(errors, "kuma", kuma_monitors, [])
    ctrs = section(errors, "docker", containers, [])
    events = section(errors, "activity", activity, [])
    kuma_up = section(errors, "kuma", kuma_alive, None)
    beszel_up = section(errors, "beszel", beszel_fresh, None)
    by_name = {m["name"].lower(): m for m in monitors}

    apps = []
    for a in cfg.get("apps", []):
        st = "unknown"
        if a.get("check") == "kuma":
            st = {True: "up", False: "down"}.get(kuma_up, "unknown")
        elif a.get("check") == "beszel":
            st = {True: "up", False: "down"}.get(beszel_up, "unknown")
        elif a.get("monitor") and a["monitor"].lower() in by_name:
            st = {1: "up", 0: "down", 2: "pending", 3: "maintenance"}.get(by_name[a["monitor"].lower()]["status"], "unknown")
        apps.append({**a, "state": st})

    problems, warnings = [], []
    for m in machines:
        if m["status"] != "up":
            problems.append(f'{m["name"]} is {m["status"]}')
    for m in monitors:
        if m["status"] == 0:
            problems.append(f'{m["name"]} is down')
        elif m["status"] == 2:
            warnings.append(f'{m["name"]} is failing checks')
    for c in ctrs:
        if c["state"] != "running":
            problems.append(f'{c["name"]} is {c["state"]}')
        elif c["health"] == "unhealthy":
            problems.append(f'{c["name"]} is unhealthy')
    if errors:
        warnings.append("Some data couldn't be loaded")
    level = "bad" if problems else "warn" if warnings else "ok"
    text = {"ok": "All systems normal",
            "warn": f"{len(warnings)} thing{'s' if len(warnings) != 1 else ''} to look at",
            "bad": f"{len(problems)} problem{'s' if len(problems) != 1 else ''}"}[level]
    server = next((m for m in machines if m["id"] == "spencer-server"), machines[0] if machines else None)
    return {
        "now": int(time.time() * 1000),
        "health": {"level": level, "text": text, "items": problems + warnings},
        "uptime": server["uptime"] if server else None,
        "apps": apps, "shortcuts": cfg.get("shortcuts", []),
        "machines": machines, "monitors": monitors, "containers": ctrs,
        "minecraft": section(errors, "minecraft", minecraft),
        "weather": section(errors, "weather", weather),
        "activity": [brief(e) for e in events[:5]], "waiting": activity_summary(events)["waiting"],
        "errors": errors,
    }


def server_detail(sslug, rng):
    m = next((x for x in beszel_systems() if x["id"] == sslug), None)
    if not m:
        return None
    return {**m, "history": beszel_history(m["bid"], rng),
            "containers": [c for c in containers() if c["host"] == sslug]}


def brief(e):
    return {k: v for k, v in e.items() if k != "raw"} if e else None


def activity_page():
    events = activity()
    return {"events": [brief(e) for e in events], "summary": activity_summary(events), "days": ACTIVITY_DAYS}


def event_detail(eid):
    events = activity()
    e = next((x for x in events if x["id"] == eid), None)
    if not e:
        return None
    same = [x for x in events if x["src"] == e["src"] and x["cat"] == e["cat"]]
    i = same.index(e)
    return {**e, "newer": brief(same[i - 1]) if i > 0 else None, "older": brief(same[i + 1]) if i + 1 < len(same) else None}


STATIC = {"/favicon.svg": ("favicon.svg", "image/svg+xml"), "/favicon.ico": ("favicon.ico", "image/x-icon"),
          "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"), "/icon-192.png": ("icon-192.png", "image/png"),
          "/icon-512.png": ("icon-512.png", "image/png"), "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def authed(self):
        tok = self.cookie("mcsess")
        with _auth_lock:
            exp = _sessions.get(tok)
        return bool(exp and exp > time.time())

    def send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if ctype == "application/json" else body).encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        rng = urllib.parse.parse_qs(u.query).get("range", ["24h"])[0]
        rng = rng if rng in RANGES else "24h"
        p = u.path
        try:
            if p == "/":
                with open(os.path.join(HERE, "index.html"), "rb") as f:
                    return self.send(200, f.read(), "text/html")
            if p in STATIC:
                name, ctype = STATIC[p]
                with open(os.path.join(HERE, name), "rb") as f:
                    return self.send(200, f.read(), ctype)
            if p == "/ping":
                return self.send(200, "ok", "text/plain")
            if p == "/api/summary":
                return self.send(200, summary())
            if p == "/api/activity":
                return self.send(200, activity_page())
            if p == "/api/minecraft":
                return self.send(200, minecraft_detail(self.authed()))
            if p == "/api/console/log":
                if not self.authed():
                    return self.send(401, {"error": "Unlock the console first."})
                q = urllib.parse.parse_qs(u.query)
                pos, ino = q.get("pos", [""])[0], q.get("ino", [""])[0]
                return self.send(200, console_log(int(pos) if pos.isdigit() else None, int(ino) if ino.isdigit() else None))
            m = re.fullmatch(r"/api/(server|monitor|container|event)/([a-z0-9-]+)", p)
            if m:
                kind, key = m.groups()
                if kind == "event":
                    data = event_detail(key)
                    return self.send(200, data) if data else self.send(404, {"error": f"No activity with that id in the last {ACTIVITY_DAYS} days."})
                data = (server_detail(key, rng) if kind == "server" else
                        kuma_detail(int(key), rng) if kind == "monitor" and key.isdigit() else
                        container_detail(key, rng) if kind == "container" else None)
                return self.send(200, data) if data else self.send(404, {"error": f"No {kind} called {key}"})
            return self.send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            log(f"{p}: {e!r}")
            return self.send(500, {"error": str(e)})

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send(415, {"error": "JSON only."})  # plain cross-site form posts can't set this
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 4096)) or b"{}")
        except ValueError:
            body = {}
        ip = self.client_address[0]
        if p == "/api/console/login":
            tok, err = login(ip, str(body.get("password", "")))
            if err:
                return self.send(403, {"error": err})
            log(f"console unlocked from {ip}")
            return self.send(200, {"ok": True}, headers={
                "Set-Cookie": f"mcsess={tok}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_DAYS * 86400}"})
        if p == "/api/console/logout":
            with _auth_lock:
                _sessions.pop(self.cookie("mcsess"), None)
            return self.send(200, {"ok": True}, headers={"Set-Cookie": "mcsess=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
        if p == "/api/console/command":
            if not self.authed():
                return self.send(401, {"error": "Unlock the console first."})
            cmd = str(body.get("cmd", ""))
            res = console_send(cmd)
            log(f"console command from {ip}: {cmd!r} -> {'ok' if res.get('ok') else res.get('error')}")
            return self.send(200 if res.get("ok") else 400, res)
        return self.send(404, {"error": "not found"})


if __name__ == "__main__":
    log(f"dashboard listening on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
