"""NYC subway trains for Spencer-Server (README 3.17): live arrivals, a live map of every line, and a trip planner.

Split out of the dashboard (which still has its Trains tab: it forwards its /api/trains* calls here).
No keys, no logins, no database, no outside Python packages.
  MTA GTFS-realtime  the eight subway feeds + service alerts, decoded by a small built-in protobuf reader
  static GTFS        stations.json, network.json (track shapes), complexes.json, made by build-network.py
  Nominatim          OpenStreetMap address search for the planner (max 1 request a second, cached an hour)
Serves:
  /                         the web app (index.html)
  /api/trains?s=c602,632&n=8   next arrivals + alerts at up to 4 stations (complex or platform-group ids)
  /api/trains/plan?from=lat,lon|cid&to=...   fastest trips on the live predictions (walk + trains + transfers)
  /api/trains/geocode?q=    address/place search in NYC
  /api/trains/map           every running train with an estimated position (all lines)
  /api/trains/network       the line segments for the map
  /api/trains/stations      every station complex + platform positions + the default stations
  /ping                     200 while the web server is up (Docker healthcheck)
  /health                   200 when the MTA feeds answer, 503 when none do (Uptime Kuma)
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "8400"))
HERE = os.path.dirname(os.path.abspath(__file__))


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


# ---------------------------------------------------------------- NYC subway trains (MTA GTFS-realtime, no key)

MTA_BASE = "https://api-endpoint.mta.info/Dataservice/mtagtfsfeeds/"
MTA_FEEDS = ["nyct%2Fgtfs", "nyct%2Fgtfs-ace", "nyct%2Fgtfs-bdfm", "nyct%2Fgtfs-g", "nyct%2Fgtfs-jz",
             "nyct%2Fgtfs-nqrw", "nyct%2Fgtfs-l", "nyct%2Fgtfs-si"]
MTA_ALERTS = "camsys%2Fsubway-alerts"
HTTPS_URL = os.environ.get("HTTPS_URL", "")      # the tailnet https address; phones need it for "use my location"
TRAIN_STATIONS = [x for x in os.environ.get("TRAIN_STATIONS", "632,631").split(",") if x.strip()]
try:
    with open(os.path.join(HERE, "stations.json")) as _f:
        STATIONS = {x["id"]: x for x in json.load(_f)}
except OSError:
    STATIONS = {}


try:
    with open(os.path.join(HERE, "complexes.json")) as _f:
        COMPLEXES = json.load(_f)
except OSError:
    COMPLEXES = []
CX = {c["id"]: c for c in COMPLEXES}
STOP2CX = {s: c["id"] for c in COMPLEXES for s in c["stops"]}


def _pb(buf):
    """Minimal protobuf reader: yields (field number, value). Value is an int, or bytes for length-delimited fields."""
    i, n = 0, len(buf)
    while i < n:
        key = shift = 0
        while True:
            b = buf[i]; i += 1
            key |= (b & 0x7F) << shift; shift += 7
            if not b & 0x80:
                break
        f, wt = key >> 3, key & 7
        if wt == 0:
            v = shift = 0
            while True:
                b = buf[i]; i += 1
                v |= (b & 0x7F) << shift; shift += 7
                if not b & 0x80:
                    break
            yield f, v
        elif wt == 2:
            ln = shift = 0
            while True:
                b = buf[i]; i += 1
                ln |= (b & 0x7F) << shift; shift += 7
                if not b & 0x80:
                    break
            yield f, buf[i:i + ln]
            i += ln
        elif wt == 1:
            yield f, int.from_bytes(buf[i:i + 8], "little"); i += 8
        elif wt == 5:
            yield f, int.from_bytes(buf[i:i + 4], "little"); i += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wt}")


def _mta_get(name):
    req = urllib.request.Request(MTA_BASE + name, headers={"User-Agent": "homelab-trains"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read()


def _parse_trips(buf):
    trips, veh = [], {}
    for f, ent in _pb(buf):
        if f != 2:
            continue
        for ef, tu in _pb(ent):
            if ef == 4:                                  # VehiclePosition: which trains are actually running right now
                tid, status, vstop, ts = "", 2, "", 0
                for vf, vv in _pb(tu):
                    if vf == 1:
                        for df, dv in _pb(vv):
                            if df == 1:
                                tid = dv.decode("utf-8", "replace")
                    elif vf == 4: status = vv
                    elif vf == 7: vstop = vv.decode("utf-8", "replace")
                    elif vf == 5: ts = vv
                if tid:
                    veh[tid] = (status, vstop, ts)
                continue
            if ef != 3:
                continue
            route = trip_id = ""
            stops = []
            for tf, v in _pb(tu):
                if tf == 1:
                    for df, dv in _pb(v):
                        if df == 1:
                            trip_id = dv.decode("utf-8", "replace")
                        elif df == 5:
                            route = dv.decode("utf-8", "replace")
                elif tf == 2:
                    sid, t = "", 0
                    for sf, sv in _pb(v):
                        if sf == 4:
                            sid = sv.decode("utf-8", "replace")
                        elif sf in (2, 3) and not t:       # arrival, else departure
                            for ef2, ev in _pb(sv):
                                if ef2 == 2:
                                    t = ev
                    if sid and t:
                        stops.append((sid, t))
            if route and stops:
                trips.append({"id": trip_id, "route": route, "stops": stops})
    for t in trips:
        t["veh"] = veh.get(t["id"])                      # None = scheduled but not started yet
    return trips


def train_trips():
    """Every scheduled/running train in the system (all eight feeds, fetched in parallel, cached 20 s)."""
    def load():
        results, errs = [], []
        def one(name):
            try:
                results.extend(_parse_trips(_mta_get(name)))
            except Exception as e:  # noqa: BLE001 - one dead feed shouldn't blank the others
                errs.append(f"{name}: {e}")
        threads = [threading.Thread(target=one, args=(n,)) for n in MTA_FEEDS]
        [t.start() for t in threads]
        [t.join(20) for t in threads]
        if not results:
            raise RuntimeError("no MTA feed answered: " + "; ".join(errs))
        return {"trips": results, "failed": len(errs), "at": int(time.time())}
    return cached("train-trips", 20, load)


def train_alerts():
    def load():
        out = []
        for f, ent in _pb(_mta_get(MTA_ALERTS)):
            if f != 2:
                continue
            for ef, al in _pb(ent):
                if ef != 5:
                    continue
                routes, stops, header, desc, periods = set(), set(), "", "", []
                for af, v in _pb(al):
                    if af == 1:
                        a = b = 0
                        for pf, pv in _pb(v):
                            if pf == 1: a = pv
                            elif pf == 2: b = pv
                        periods.append((a, b))
                    elif af == 5:
                        for sf, sv in _pb(v):
                            if sf == 2: routes.add(sv.decode())
                            elif sf == 5: stops.add(sv.decode())
                    elif af in (10, 11):
                        for tf, tv in _pb(v):
                            if tf == 1:
                                txt = ""
                                for xf, xv in _pb(tv):
                                    if xf == 1: txt = xv.decode("utf-8", "replace")
                                if af == 10 and not header: header = txt
                                elif af == 11 and not desc: desc = txt
                now = time.time()
                if periods and not any((a == 0 or a <= now) and (b == 0 or b >= now) for a, b in periods):
                    continue                                   # scheduled for later (or already over)
                if header:
                    clean = lambda x: re.sub(r"\[([A-Z0-9]+)\]", r"\1", x)
                    out.append({"routes": sorted(routes), "stops": sorted(stops), "header": clean(header), "desc": clean(desc)})
        return out
    return cached("train-alerts", 60, load)


def station_name(stop_id):
    s = STATIONS.get(stop_id[:-1] if stop_id[-1:] in "NS" else stop_id)
    return s["name"] if s else stop_id


def trains_at(ids, limit=8):
    """Next trains at up to four station complexes. An id may be a complex ("c602") or a single platform group ("635");
    a complex merges every platform group in it (all three Union Sq stations are one place)."""
    data = train_trips()
    now = time.time()
    try:
        alerts = train_alerts()
    except Exception as e:  # noqa: BLE001
        log(f"train alerts: {e}")
        alerts = []
    cxs = []
    for i in ids:
        c = i if i in CX else STOP2CX.get(i)
        if c and c not in cxs:
            cxs.append(c)
    stations = []
    for cid in cxs:
        c = CX[cid]
        stops = set(c["stops"])
        dirs = {"N": [], "S": []}
        routes = set()
        for tr in data["trips"]:
            for stop, t in tr["stops"]:
                if stop[:-1] in stops and stop[-1] in dirs and now - 30 <= t <= now + 3600:
                    dirs[stop[-1]].append({"route": tr["route"], "t": t * 1000, "to": station_name(tr["stops"][-1][0]), "trip": tr["id"]})
                    routes.add(tr["route"])
                    break
        for d in dirs.values():
            d.sort(key=lambda a: a["t"])
        mine = [a for a in alerts if routes & set(a["routes"]) or any(x in stops or x[:-1] in stops for x in a["stops"])]
        stations.append({"id": cid, "name": c["name"], "lat": c["lat"], "lon": c["lon"], "routes": sorted(routes, key=lambda r: (r.rstrip("X"), r)),
                         "north": dirs["N"][:limit], "south": dirs["S"][:limit], "alerts": mine[:6]})
    return {"now": int(now * 1000), "feed_at": data["at"] * 1000, "feeds_down": data["failed"], "stations": stations}


try:
    with open(os.path.join(HERE, "network.json")) as _f:
        NETWORK = json.load(_f)
except OSError:
    NETWORK = {"edges": [], "pred": {}}


STATION_ROUTES = {}
for _r, _dirs in NETWORK["pred"].items():
    for _m in _dirs.values():
        for _b, _a in _m.items():
            STATION_ROUTES.setdefault(_b, set()).add(_r)
            STATION_ROUTES.setdefault(_a, set()).add(_r)
STATION_ROUTES = {k: sorted(v, key=lambda r: (r.rstrip("X"), r)) for k, v in STATION_ROUTES.items()}


# Track geometry between neighbouring stations ("A|B" with A < B) and each piece's running length, so a train
# that is x% of the way from A to B is drawn x% of the way along the real curve, not on the straight line.
SEGS = {}
for _k, _pts in NETWORK.get("segs", {}).items():
    _cum = [0.0]
    for _p, _q in zip(_pts, _pts[1:]):
        _cum.append(_cum[-1] + (((_p[0] - _q[0]) * 111.0) ** 2 + ((_p[1] - _q[1]) * 84.0) ** 2) ** 0.5)
    SEGS[tuple(_k.split("|"))] = (_pts, _cum)


def _along(a, b, frac):
    """Point frac of the way from station a to station b, following the track when we have it."""
    if a is b or a["id"] == b["id"]:
        return a["lat"], a["lon"]
    flip = a["id"] > b["id"]
    seg = SEGS.get((b["id"], a["id"]) if flip else (a["id"], b["id"]))
    if not seg or seg[1][-1] <= 0:
        return a["lat"] + (b["lat"] - a["lat"]) * frac, a["lon"] + (b["lon"] - a["lon"]) * frac
    pts, cum = seg
    want = (1 - frac if flip else frac) * cum[-1]
    for i in range(1, len(cum)):
        if cum[i] >= want:
            f = (want - cum[i - 1]) / ((cum[i] - cum[i - 1]) or 1)
            return pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * f, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * f
    return pts[-1][0], pts[-1][1]


def _km(a, b):
    dy = (a["lat"] - b["lat"]) * 111.0
    dx = (a["lon"] - b["lon"]) * 84.0
    return (dx * dx + dy * dy) ** 0.5


def trains_map():
    """Every running train with an estimated position. The MTA gives times, not coordinates: a train is placed between
    its previous and next station by how far through that gap the clock says it is (straight line between stations)."""
    data = train_trips()
    now = time.time()
    out = []
    for tr in data["trips"]:
        if not tr["veh"]:
            continue
        stops = tr["stops"]
        d = stops[0][0][-1:]
        pred = NETWORK["pred"].get(tr["route"], {}).get(d, {})
        i = next((k for k, (_, t) in enumerate(stops) if t >= now), len(stops))
        ta = tb = now
        if i >= len(stops):
            a = b = STATIONS.get(stops[-1][0][:-1])
            frac = 0.0
        else:
            b = STATIONS.get(stops[i][0][:-1])
            if i > 0:
                a = STATIONS.get(stops[i - 1][0][:-1])
                span = stops[i][1] - stops[i - 1][1]
                frac = (now - stops[i - 1][1]) / span if span > 0 else 1.0
                ta, tb = stops[i - 1][1], stops[i][1]
            else:
                a = STATIONS.get(pred.get(stops[0][0][:-1], ""))
                if a and b:
                    seg = max(60.0, _km(a, b) / 0.0075)       # ~27 km/h average between stops
                    frac = 1.0 - (stops[0][1] - now) / seg
                    ta, tb = stops[0][1] - seg, stops[0][1]
                else:
                    a, frac = b, 0.0
            if tr["veh"][0] == 1 and tr["veh"][1]:        # the feed says it is standing in a station
                here = STATIONS.get(tr["veh"][1][:-1])
                if here:
                    a = b = here
                    ta = tb = now
        if not a or not b:
            continue
        frac = max(0.0, min(1.0, frac))
        nxt = stops[i] if i < len(stops) else stops[-1]
        here = a if a is b or frac <= 0.03 else b if frac >= 0.97 else None   # standing (or as good as) at a station
        at = STOP2CX.get(here["id"]) if here else None
        lat, lon = _along(a, b, frac)
        out.append({"id": tr["id"], "route": tr["route"], "dir": d, "lat": round(lat, 5), "lon": round(lon, 5),
                    "a": a["id"], "b": b["id"], "ta": int(ta * 1000), "tb": int(tb * 1000),     # the page moves the dot along the track itself
                    "to": station_name(stops[-1][0]), "next": station_name(nxt[0]), "eta": nxt[1] * 1000, "at": at})
    return {"now": int(now * 1000), "feeds_down": data["failed"], "trains": out}


# ---------------------------------------------------------------- trip planner (fastest trip on the live predictions)

WALK_M_PER_MIN = 80          # ~4.8 km/h
WALK_DETOUR = 1.3            # streets aren't straight lines
WALK_MAX_M = 1600            # consider stations up to ~1 mile from either end
ENTER_MIN, EXIT_MIN = 2, 1   # street to platform, platform to street


def _m(lat1, lon1, lat2, lon2):
    return (((lat1 - lat2) * 111000) ** 2 + ((lon1 - lon2) * 84000) ** 2) ** 0.5


def _walk_min(d):
    return d * WALK_DETOUR / WALK_M_PER_MIN


# Transfers: the same platform group 2 min; another platform group of the same complex or a station within 350 m: walk + 3 min.
NEAR = {}
_ids = list(STATIONS)
for _a in _ids:
    sa, lst = STATIONS[_a], [(_a, 2.0)]
    for _b in _ids:
        if _b == _a:
            continue
        sb = STATIONS[_b]
        d = _m(sa["lat"], sa["lon"], sb["lat"], sb["lon"])
        if d <= 350 or (STOP2CX.get(_a) and STOP2CX.get(_a) == STOP2CX.get(_b)):
            lst.append((_b, max(3.0, _walk_min(d) + 3)))
    NEAR[_a] = lst


def train_connections():
    """Every hop of every upcoming train (dep, arr, from station, to station, trip #, stop #), sorted by departure."""
    def load():
        trips = train_trips()["trips"]
        conns = []
        for ti, tr in enumerate(trips):
            st = tr["stops"]
            for k in range(len(st) - 1):
                (a, ta), (b, tb) = st[k], st[k + 1]
                if tb >= ta and a[:-1] in STATIONS and b[:-1] in STATIONS:
                    conns.append((ta, tb, a[:-1], b[:-1], ti, k))
        conns.sort()
        return {"trips": trips, "conns": conns, "deps": [c[0] for c in conns]}
    return cached("train-conns", 20, load)


def _ends(spec, start):
    """'40.75,-73.98' or a station complex id -> [(station, walk minutes)] around that point, nearest first."""
    if spec in CX:
        return [(sid, 0.0) for sid in CX[spec]["stops"] if sid in STATIONS], (CX[spec]["lat"], CX[spec]["lon"])
    lat, lon = (float(x) for x in spec.split(","))
    out = []
    for sid, sv in STATIONS.items():
        d = _m(lat, lon, sv["lat"], sv["lon"])
        if d <= WALK_MAX_M:
            out.append((sid, _walk_min(d) + (ENTER_MIN if start else EXIT_MIN)))
    out.sort(key=lambda x: x[1])
    return out[:16], (lat, lon)


def _csa(data, origin, dest, now, exclude):
    """Connection-scan for the earliest arrival. origin: [(station, walk min)], dest: {station: walk min}."""
    import bisect
    conns, INF = data["conns"], float("inf")
    ready, ready_how, arrive, arrive_how, boarded = {}, {}, {}, {}, {}
    for sid, w in origin:
        t = now + w * 60
        if t < ready.get(sid, INF):
            ready[sid], ready_how[sid] = t, ("start", w)
    best, best_st = INF, None
    for c in conns[bisect.bisect_left(data["deps"], now):]:
        dep, arr, a, b, ti, _k = c
        if dep > best:
            break
        if ti in exclude:
            continue
        if ti not in boarded:
            if ready.get(a, INF) > dep:
                continue
            boarded[ti] = c
        if arr < arrive.get(b, INF):
            arrive[b], arrive_how[b] = arr, (boarded[ti], c)
            if b in dest and arr + dest[b] * 60 < best:
                best, best_st = arr + dest[b] * 60, b
            for nb, mins in NEAR.get(b, ()):
                t = arr + mins * 60
                if t < ready.get(nb, INF):
                    ready[nb], ready_how[nb] = t, ("xfer", b, mins)
    if best_st is None:
        return None
    trips, legs, st = data["trips"], [], best_st
    legs.append({"type": "walk", "min": round(dest[best_st]), "to": "destination"})
    first_trip = None
    while True:
        on, off = arrive_how[st]
        tr = trips[on[4]]
        legs.append({"type": "ride", "route": tr["route"], "dir": tr["stops"][0][0][-1:], "headsign": station_name(tr["stops"][-1][0]),
                     "from": station_name(on[2]), "to": station_name(off[3]), "from_id": STOP2CX.get(on[2]), "to_id": STOP2CX.get(off[3]),
                     "dep": int(on[0] * 1000), "arr": int(off[1] * 1000), "stops": off[5] - on[5] + 1,
                     "_via": [STOP2CX.get(sid[:-1], sid[:-1]) for sid, _ in tr["stops"][on[5]:off[5] + 2]],
                     "path": [sid[:-1] for sid, _ in tr["stops"][on[5]:off[5] + 2]], "trip": tr["id"]})
        first_trip = on[4]
        how = ready_how[on[2]]
        if how[0] == "start":
            legs.append({"type": "walk", "min": round(how[1]), "to": station_name(on[2]), "start": True})
            break
        prev = how[1]
        legs.append({"type": "transfer", "min": round(how[2]), "at": station_name(prev), "to": station_name(on[2]), "walk": prev != on[2]})
        st = prev
    legs.reverse()
    # The scan boards a train at the first station where you could catch it. If that same train also stops at
    # another station near the start, board it wherever you can leave latest (and on a tie, walk least):
    # don't walk 13 min north to 42 St for a D that comes down to 34 St two minutes later.
    if legs[0]["type"] == "walk" and legs[0].get("start") and legs[1]["type"] == "ride":
        ride, walk_from = legs[1], dict(origin)
        tr = trips[first_trip]
        k0 = next(k for k, (sid, t) in enumerate(tr["stops"]) if int(t * 1000) == ride["dep"] and station_name(sid) == ride["from"])
        k_off = k0 + ride["stops"] - 1
        best_k, best_key = k0, None
        for k in range(k0, k_off):
            sid, t = tr["stops"][k]
            w = walk_from.get(sid[:-1])
            if w is None:
                continue
            key = (t - w * 60, -w)                      # leave latest, then walk least
            if best_key is None or key > best_key:
                best_k, best_key = k, key
        if best_k != k0:
            sid, t = tr["stops"][best_k]
            ride.update({"from": station_name(sid), "from_id": STOP2CX.get(sid[:-1]), "dep": int(t * 1000), "stops": k_off - best_k + 1,
                         "_via": [STOP2CX.get(x[:-1], x[:-1]) for x, _ in tr["stops"][best_k:k_off + 2]],
                         "path": [x[:-1] for x, _ in tr["stops"][best_k:k_off + 2]]})
            legs[0].update({"min": round(walk_from[sid[:-1]]), "to": station_name(sid)})
    first_dep = next(l["dep"] for l in legs if l["type"] == "ride")
    leave = first_dep - legs[0]["min"] * 60000 if legs[0]["type"] == "walk" else first_dep
    return {"legs": legs, "arrive": int(best * 1000), "leave": int(leave), "first_trip": first_trip}


def trip_plan(qs):
    f, t = qs.get("from", [""])[0], qs.get("to", [""])[0]
    if not f or not t:
        return {"error": "Give a start and a destination."}
    now = time.time()
    origin, o_pt = _ends(f, True)
    dest_list, d_pt = _ends(t, False)
    if not origin or not dest_list:
        return {"error": "No subway station within about a mile of " + ("the start." if not origin else "the destination."), "options": []}
    dest = {}
    for sid, w in dest_list:
        dest[sid] = min(w, dest.get(sid, 99))
    data = train_connections()
    trips = data["trips"]
    rides = lambda x: [l for l in x["legs"] if l["type"] == "ride"]
    walked = lambda x: sum(l["min"] for l in x["legs"] if l["type"] == "walk" or (l["type"] == "transfer" and l.get("walk")))
    sig_of = lambda x: tuple((l["from_id"], l["to_id"]) for l in rides(x))     # same stations = same trip, the 4 or the 5 alike

    def loops(x):                                      # rides back through a station it already passed (4 uptown, 5 back down)
        seen, bad = set(), False
        for l in rides(x):
            via = l.pop("_via", [])
            bad = bad or bool(seen & set(via[1:]))
            seen |= set(via)
        return bad

    # Option 1 is the fastest trip. Each alternative is a genuinely different way: search again without the lines
    # the earlier options start on (so after "D/N from Herald Sq" comes e.g. "Q, change to the R"). For every option,
    # the same stations on later trains fold in as "also 5:50, 5:58".
    opts, banned = [], set()
    for _ in range(6):
        if len(opts) >= 3:
            break
        ex = {i for i, tr in enumerate(trips) if tr["route"].rstrip("X") in banned}
        o = _csa(data, origin, dest, now, ex)
        if not o:
            break
        ex.add(o.pop("first_trip"))
        banned.add(rides(o)[0]["route"].rstrip("X"))
        if loops(o):
            continue
        sig, later = sig_of(o), []
        for _ in range(4):                             # later trains for the same trip
            o2 = _csa(data, origin, dest, now, ex)
            if not o2:
                break
            ex.add(o2.pop("first_trip"))
            if loops(o2) or sig_of(o2) != sig:
                continue
            if o2["arrive"] <= o["arrive"] and o2["leave"] > o["leave"]:
                o, o2 = o2, o                          # a later train that gets there as early leads (N 5:58 vs D 5:56, both 6:23)
            f2 = rides(o2)[0]
            if f2["dep"] != rides(o)[0]["dep"] and all(x["dep"] != f2["dep"] for x in later):
                later.append({"dep": f2["dep"], "route": f2["route"], "leave": o2["leave"], "arrive": o2["arrive"]})
            banned.add(f2["route"].rstrip("X"))
        later = [x for x in later if x["dep"] != rides(o)[0]["dep"]]
        o["later"] = sorted(later, key=lambda x: x["dep"])[:2]
        if opts:
            best = opts[0]
            if o["arrive"] - best["arrive"] > 20 * 60000 or walked(o) > walked(best) + 10:
                continue                               # far slower, or a lot more walking: not a real alternative
            o["slower_min"] = round((o["arrive"] - best["arrive"]) / 60000)
        o["changes"] = len(rides(o)) - 1
        opts.append(o)
    walk = _walk_min(_m(o_pt[0], o_pt[1], d_pt[0], d_pt[1]))
    return {"now": int(now * 1000), "options": opts, "walk_min": round(walk), "from": list(o_pt), "to": list(d_pt),
            "note": None if opts else "No train gets there within the time the live feeds cover (about the next hour)."}


_geo_lock, _geo_last = threading.Lock(), [0.0]


def geocode(qs):
    """Address/place search limited to the five boroughs, via OpenStreetMap Nominatim (free, max 1 request a second)."""
    q = qs.get("q", [""])[0].strip()[:120]
    if len(q) < 3:
        return {"results": []}
    def load():
        with _geo_lock:
            wait = 1.05 - (time.time() - _geo_last[0])
            if wait > 0:
                time.sleep(wait)
            _geo_last[0] = time.time()
            url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                {"q": q, "format": "jsonv2", "limit": 6, "countrycodes": "us", "bounded": 1,
                 "viewbox": "-74.27,40.92,-73.68,40.49", "addressdetails": 0})
            req = urllib.request.Request(url, headers={"User-Agent": "homelab-trains/1.0 (personal trip planner)"})
            with urllib.request.urlopen(req, timeout=8) as r:
                rows = json.load(r)
        out = []
        for x in rows:
            parts = [p.strip() for p in x.get("display_name", "").split(",")]
            lat, lon = float(x["lat"]), float(x["lon"])
            if any(_m(lat, lon, o["lat"], o["lon"]) < 40 for o in out):
                continue                                  # the same building listed several times (e.g. its tenants)
            out.append({"name": ", ".join(parts[:3]), "lat": lat, "lon": lon})
        return {"results": out}
    return cached("geo:" + q.lower(), 3600, load)


def trains_page(qs):
    ids = [x for x in (qs.get("s", [""])[0] or ",".join(TRAIN_STATIONS)).split(",") if x in CX or x in STOP2CX][:4]
    n = qs.get("n", ["8"])[0]
    return trains_at(ids, min(60, int(n)) if n.isdigit() and int(n) > 0 else 8)


def stations_payload():
    return {"default": [STOP2CX.get(x, x) for x in TRAIN_STATIONS], "https_url": HTTPS_URL,
            "stations": [{"id": c["id"], "name": c["name"], "lat": c["lat"], "lon": c["lon"], "stops": c["stops"],
                          "routes": sorted({r for sid in c["stops"] for r in STATION_ROUTES.get(sid, [])}, key=lambda r: (r.rstrip("X"), r))}
                         for c in COMPLEXES],
            "stops": {k: [v["lat"], v["lon"]] for k, v in STATIONS.items()}}


STATIC = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/favicon.svg": ("favicon.svg", "image/svg+xml"), "/apple-touch-icon.png": ("apple-touch-icon.png", "image/png"),
          "/icon-192.png": ("icon-192.png", "image/png"), "/icon-512.png": ("icon-512.png", "image/png"),
          "/manifest.webmanifest": ("manifest.webmanifest", "application/manifest+json")}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body, ensure_ascii=False) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/json")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        p, qs = u.path, urllib.parse.parse_qs(u.query)
        try:
            if p in STATIC:
                name, ctype = STATIC[p]
                with open(os.path.join(HERE, name), "rb") as f:
                    return self.send(200, f.read(), ctype)
            if p == "/ping":
                return self.send(200, "ok", "text/plain")
            if p == "/health":
                try:
                    d = train_trips()
                    return self.send(200, {"ok": True, "trips": len(d["trips"]), "feeds_down": d["failed"]})
                except Exception as e:  # noqa: BLE001
                    return self.send(503, {"ok": False, "error": str(e)})
            if p == "/api/trains":
                return self.send(200, trains_page(qs))
            if p == "/api/trains/plan":
                return self.send(200, trip_plan(qs))
            if p == "/api/trains/geocode":
                return self.send(200, geocode(qs))
            if p == "/api/trains/map":
                return self.send(200, trains_map())
            if p == "/api/trains/network":
                return self.send(200, {"edges": NETWORK["edges"], "segs": NETWORK.get("segs", {})})
            if p == "/api/trains/stations":
                return self.send(200, stations_payload())
            return self.send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            log(f"{p}: {e!r}")
            return self.send(500, {"error": str(e)})


if __name__ == "__main__":
    log(f"trains listening on :{PORT} ({len(COMPLEXES)} stations)")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
