#!/usr/bin/env python3
"""Builds stations.json and network.json from the MTA's static GTFS (https://rrgtfsfeeds.s3.amazonaws.com/gtfs_subway.zip).
Usage: build-network.py gtfs_subway.zip      (run when the MTA renumbers stations or adds lines; then rebuild the dashboard)
complexes.json = stations that share a complex (e.g. the three Union Sq platforms) merged into one entry; the grouping comes from the MTA's
                 "Subway Stations" open dataset (data.ny.gov 39hk-dx4f), downloaded by this script.
network.json = {"edges": [[stationA, stationB, colour-group], ...] for drawing the lines on the Trains map,
                "pred":  {route: {"N"|"S": {station: previous station}}} for placing a moving train between two stations}."""
import csv, io, json, sys, urllib.request, zipfile
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
route_of = {r["trip_id"]: r["route_id"] for r in rd("trips.txt")}
seqs = defaultdict(list)
for r in rd("stop_times.txt"):
    seqs[r["trip_id"]].append((int(r["stop_sequence"]), r["stop_id"]))
edges, pred = set(), defaultdict(lambda: defaultdict(Counter))
for tid, lst in seqs.items():
    route = route_of.get(tid)
    if route not in GROUP:
        continue
    lst.sort()
    d = lst[0][1][-1]
    st = [parent[s] for _, s in lst]
    for a, b in zip(st, st[1:]):
        if a == b:
            continue
        edges.add((min(a, b), max(a, b), GROUP[route]))
        pred[(route, d)][b][a] += 1
out = {"edges": sorted(edges), "pred": {}}
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
cx = []
for cid, rs in groups.items():
    main = max(rs, key=lambda r: len(r["daytime_routes"].split()))        # the platform group with the most lines names the complex
    cx.append({"id": "c" + cid, "name": main["stop_name"], "stops": sorted(r["gtfs_stop_id"] for r in rs),
               "lat": round(sum(float(known[r["gtfs_stop_id"]]["stop_lat"]) for r in rs) / len(rs), 5),
               "lon": round(sum(float(known[r["gtfs_stop_id"]]["stop_lon"]) for r in rs) / len(rs), 5)})
for sid, r in known.items():                                              # a station the dataset doesn't know stands alone
    if sid not in seen:
        cx.append({"id": "s" + sid, "name": r["stop_name"], "stops": [sid], "lat": round(float(r["stop_lat"]), 5), "lon": round(float(r["stop_lon"]), 5)})
json.dump(cx, open("complexes.json", "w"), separators=(",", ":"))
print(len(cx), "complexes")
