#!/usr/bin/env python3
"""Fetch and trim the OpenStreetMap data used to calibrate the VIT-AP map.

Writes data/osm/vitap_osm_extract.json, the committed reference that
scripts/calibrate_campus_from_osm.py and tests/test_coordinate_integrity.py read.
Only needed to refresh the extract; normal runs never touch the network.

Data (c) OpenStreetMap contributors, ODbL 1.0: https://www.openstreetmap.org/copyright

Usage: python scripts/fetch_osm_extract.py
"""

import json
import urllib.request
from datetime import date
from pathlib import Path

# (min_lon, min_lat, max_lon, max_lat) of the area downloaded from the OSM API.
BBOX = (80.490, 16.486, 80.508, 16.500)
# Ways kept for routing geometry: everything a vehicle or pedestrian can use on campus.
DRIVE = {"secondary", "tertiary", "unclassified", "residential", "service"}
WALK_ONLY = {"footway", "path", "pedestrian", "steps"}
# Building/parking ways the config references directly (exact positions).
REFERENCED_WAYS = {
    750542242, 1255690439, 1321555307, 1434460208, 1434908865, 1434460210, 1485935404,
    1434460214, 1434890457, 1485935405, 1485919486,  # destinations
    1485919489, 1485919490,                           # overflow parking
}
# Multipolygon buildings (name/tags live on the relation; geometry in its member ways).
REFERENCED_RELATIONS = {20292102, 20292198, 20292199, 20292200}  # MH-5, MH-4, LH-2, LH-3
OUT = Path(__file__).resolve().parent.parent / "data" / "osm" / "vitap_osm_extract.json"


def main():
    url = "https://api.openstreetmap.org/api/0.6/map.json?bbox=" + ",".join(map(str, BBOX))
    req = urllib.request.Request(url, headers={"User-Agent": "campus-map-calibration/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)

    nodes = {e["id"]: e for e in data["elements"] if e["type"] == "node"}
    ways = {e["id"]: e for e in data["elements"] if e["type"] == "way"}

    rels = {e["id"]: e for e in data["elements"] if e["type"] == "relation"}
    missing_rel = REFERENCED_RELATIONS - set(rels)
    if missing_rel:
        raise SystemExit(f"Referenced OSM relations missing from download: {sorted(missing_rel)}")
    rel_ways = {m["ref"] for r in REFERENCED_RELATIONS for m in rels[r]["members"] if m["type"] == "way"}

    kept = {}
    for wid, w in ways.items():
        tags = w.get("tags", {})
        if wid in REFERENCED_WAYS or wid in rel_ways or tags.get("highway") in (DRIVE | WALK_ONLY):
            kept[wid] = {"tags": tags, "nodes": w["nodes"]}
    missing = REFERENCED_WAYS - set(kept)
    if missing:
        raise SystemExit(f"Referenced OSM ways missing from download: {sorted(missing)}")

    used = {n for w in kept.values() for n in w["nodes"]}
    out = {
        "_meta": {
            "source": "OpenStreetMap API 0.6 /map",
            "license": "ODbL 1.0, (c) OpenStreetMap contributors",
            "fetched": date.today().isoformat(),
            "bbox_lon_lat": list(BBOX),
        },
        "nodes": {str(n): [nodes[n]["lat"], nodes[n]["lon"]] for n in sorted(used) if n in nodes},
        "ways": {str(i): kept[i] for i in sorted(kept)},
        "relations": {str(r): {"tags": rels[r].get("tags", {}),
                               "members": [{"ref": m["ref"], "role": m["role"]}
                                           for m in rels[r]["members"] if m["type"] == "way"]}
                      for r in sorted(REFERENCED_RELATIONS)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB): {len(out['ways'])} ways, {len(out['relations'])} relations, {len(out['nodes'])} nodes")


if __name__ == "__main__":
    main()
