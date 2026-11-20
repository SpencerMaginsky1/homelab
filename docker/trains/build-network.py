#!/usr/bin/env python3
"""Builds stations.json and network.json from the MTA's static GTFS (https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip).
Usage: build-network.py gtfs_subway.zip      (run when the MTA renumbers stations or adds lines; then rebuild the dashboard)
complexes.json = stations that share a complex (e.g. the three Union Sq platforms) merged into one entry; the grouping comes from the MTA's
                 "Subway Stations" open dataset (data.ny.gov 39hk-dx4f), downloaded by this script.
network.json = {"edges": [[stationA, stationB, colour-group], ...] for drawing the lines on the Trains map,
                "segs":  {"A|B": [[lat, lon], ...]} the real track between two neighbouring stations (A < B), cut from the
                         MTA's shapes.txt, so lines and moving trains follow the curves,
                "pred":  {route: {"N"|"S": {station: previous station}}} for placing a moving train between two stations}."""
import csv, io, json, math, sys, urllib.request, zipfile
from collections import Counter, defaultdict

GROUP = {**dict.fromkeys(["1", "2", "3"], "123"), **dict.fromkeys(["4", "5", "6", "6X"], "456"), **dict.fromkeys(["7", "7X"], "7"),
         **dict.fromkeys(["A", "C", "E", "H", "FS"], "ACE"), **dict.fromkeys(["B", "D", "F", "FX", "M"], "BDFM"), "G": "G",
         **dict.fromkeys(["J", "Z"], "JZ"), "L": "L", **dict.fromkeys(["N", "Q", "R", "W"], "NQRW"), "GS": "S", "SI": "SI"}
z = zipfile.ZipFile(sys.argv[1])
rd = lambda n: csv.DictReader(io.TextIOWrapper(z.open(n), encoding="utf-8-sig"))
stops = list(rd("stops.txt"))
json.dump([{"id": r["stop_id"], "name": r["stop_name"], "lat": round(float(r["stop_lat"]), 5), "lon": round(float(r["stop_lon"]), 5)}
           for r in stops if r["location_type"] == "1"], open("stations.json", "w"), separators=(",", ":"))
parent = {r["stop_id"]: (r["parent_station"] or r["stop_id"]) for r in stops}
trips_rows = list(rd("trips.txt"))
route_of = {r["trip_id"]: r["route_id"] for r in trips_rows}
shape_of = {r["trip_id"]: r["shape_id"] for r in trips_rows}
pos = {r["stop_id"]: (float(r["stop_lat"]), float(r["stop_lon"])) for r in stops}
seqs = defaultdict(list)
for r in rd("stop_times.txt"):
    seqs[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"]))
edges, pred, patterns = set(), defaultdict(lambda: defaultdict(Counter)), set()
for tid, lst in seqs.items():
    route = route_of.get(tid)
    if route not in GROUP:
        continue
    lst.sort()
    d = lst[0][1][-1]
    st = [parent[s] for _, s in lst]
    if shape_of.get(tid):
        patterns.add((shape_of[tid], tuple(st)))
    for a, b in zip(st, st[1:]):
        if a == b:
            continue
        edges.add((min(a, b), max(a, b), GROUP[route]))
        pred[(route, d)][b][a] += 1
# ---- track geometry: for each pair of neighbouring stations, the piece of a real shape between them
shapes = defaultdict(list)
for r in rd("shapes.txt"):
    shapes[r["shape_id"]].append((int(r["shape_pt_sequence"]), float(r["shape_pt_lat"]), float(r["shape_pt_lon"])))
shapes = {k: [(la, lo) for _, la, lo in sorted(v)] for k, v in shapes.items()}
M = lambda p, q: math.hypot((p[0] - q[0]) * 111000, (p[1] - q[1]) * 84000)    # metres, good enough at NYC's latitude

def nearest(pts, p, start=0):
    best, bi = 1e18, start
    for i in range(start, len(pts)):
        d = M(pts[i], p)
        if d < best:
            best, bi = d, i
    return bi, best

def simplify(pts, tol=4.0):                     # Douglas-Peucker in metres
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    ab = M(a, b) or 1e-9
    def dist(p):
        ax, ay = (p[1] - a[1]) * 84000, (p[0] - a[0]) * 111000
        bx, by = (b[1] - a[1]) * 84000, (b[0] - a[0]) * 111000
        return abs(ax * by - ay * bx) / ab
    i, d = max(((k, dist(pts[k])) for k in range(1, len(pts) - 1)), key=lambda x: x[1])
    if d <= tol:
        return [a, b]
    return simplify(pts[:i + 1], tol)[:-1] + simplify(pts[i:], tol)

segs = {}
for sid, seq in sorted(patterns):
    pts = shapes.get(sid)
    if not pts:
        continue
    cur = 0
    for a, b in zip(seq, seq[1:]):
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        ia, da = nearest(pts, pos[a], cur)
        ib, db = nearest(pts, pos[b], ia)
        cur = ia
        if key in segs or da > 150 or db > 150 or ib <= ia:
            continue
        piece = [pos[a]] + pts[ia + 1:ib] + [pos[b]]
        piece = simplify(piece)
        if a != key[0]:
            piece = piece[::-1]
        segs[key] = [[round(la, 5), round(lo, 5)] for la, lo in piece]

out = {"edges": sorted(edges), "pred": {}, "segs": {f"{a}|{b}": v for (a, b), v in segs.items()}}
print(len(segs), "curved segments for", len({(a, b) for a, b, _ in edges}), "station pairs")
for (route, d), m in pred.items():
    out["pred"].setdefault(route, {})[d] = {b: c.most_common(1)[0][0] for b, c in m.items()}
json.dump(out, open("network.json", "w"), separators=(",", ":"))
print(len(edges), "edges;", len(out["pred"]), "routes")

# ---- complexes: one dot per station complex
URL = "https://data.ny.gov/resource/39hk-dx4f.json?$limit=2000&$select=gtfs_stop_id,complex_id,stop_name,daytime_routes,gtfs_latitude,gtfs_longitude"
rows = json.load(urllib.request.urlopen(URL, timeout=60))
known = {r["stop_id"]: r for r in stops if r["location_type"] == "1"}
groups = defaultdict(list)
for r in rows:
    if r["gtfs_stop_id"] in known:
        groups[r["complex_id"]].append(r)
seen = {r["gtfs_stop_id"] for r in rows}
SPLIT_M = 250    # platforms further apart than this (about an avenue block) are separate places on the map, e.g. Times Sq vs Port Authority
def clusters(rs):
    out = [[r] for r in rs]
    merged = True
    while merged:
        merged = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                if min(M(pos[a["gtfs_stop_id"]], pos[b["gtfs_stop_id"]]) for a in out[i] for b in out[j]) < SPLIT_M:
                    out[i] += out.pop(j); merged = True; break
            if merged:
                break
    return out
cx = []
for cid, all_rs in groups.items():
    parts = sorted(clusters(all_rs), key=lambda g: -sum(len(r["daytime_routes"].split()) for r in g))
    for n, rs in enumerate(parts):
        main = max(rs, key=lambda r: len(r["daytime_routes"].split()))    # the platform group with the most lines names the place
        cx.append({"id": "c" + cid + ("" if n == 0 else f"-{n}"), "name": main["stop_name"], "stops": sorted(r["gtfs_stop_id"] for r in rs),
                   "lines": sorted({x for r in rs for x in r["daytime_routes"].split()}),
                   "lat": round(sum(pos[r["gtfs_stop_id"]][0] for r in rs) / len(rs), 5),
                   "lon": round(sum(pos[r["gtfs_stop_id"]][1] for r in rs) / len(rs), 5)})
for sid, r in known.items():                                              # a station the dataset doesn't know stands alone
    if sid not in seen:
        cx.append({"id": "s" + sid, "name": r["stop_name"], "stops": [sid], "lat": round(float(r["stop_lat"]), 5), "lon": round(float(r["stop_lon"]), 5)})
for c in cx:                                   # two "34 St-Penn Station"s an avenue apart: add the lines, "34 St-Penn Station (A C E)"
    twins = [o for o in cx if o is not c and o["name"] == c["name"] and M((o["lat"], o["lon"]), (c["lat"], c["lon"])) < 800]
    if twins and c.get("lines"):
        c["label"] = f'{c["name"]} ({" ".join(c["lines"])})'
for c in cx:
    c["name"] = c.pop("label", c["name"])
    c.pop("lines", None)
json.dump(cx, open("complexes.json", "w"), separators=(",", ":"))
print(len(cx), "complexes")
