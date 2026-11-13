#!/usr/bin/env python3
"""Calibrate configs/campus/vitap.yaml against OpenStreetMap + the reference map.

Inputs  : configs/campus/vitap_calibration.yaml  (what may be placed, and from what)
          data/osm/vitap_osm_extract.json        (OSM ways/nodes, ODbL)
Rewrites: configs/campus/vitap.yaml (coordinates, provenance, boundaries, road geometry)

What it does
  1. exact points     -> OSM way centroid (never overwritten by an estimate)
  2. approximate pts  -> pixel position through an affine transform fitted to exact
                         control points; the fit is validated (leave-one-out) first
  3. road geometry    -> shortest path along real OSM roads between the two end nodes
                         (vehicle roads for drivable links, vehicle + footways for walk links)
  4. unconfigured     -> destinations with no reference are kept in the graph/DB but left
                         UNPLACED (no coordinates, not drawn). They must stay: the seeded
                         simulation draws each vehicle's destination from the destinations
                         table, so deleting them changes every experiment result.

It deliberately NEVER touches length_meters, expected_travel_time_seconds or edge
weights: routing costs stay exactly as committed so experiment results remain
reproducible. Geometry length may therefore differ from the declared length; those
differences are listed in docs/road_length_discrepancies.md, not "fixed".

Usage:
  python scripts/calibrate_campus_from_osm.py                 # dry run, prints summary
  python scripts/calibrate_campus_from_osm.py --apply --before <old vitap.yaml> --docs docs
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "campus" / "vitap.yaml"
SPEC = ROOT / "configs" / "campus" / "vitap_calibration.yaml"
EXTRACT = ROOT / "data" / "osm" / "vitap_osm_extract.json"

DRIVE_HW = {"secondary", "tertiary", "unclassified", "residential", "service"}
WALK_HW = DRIVE_HW | {"footway", "path", "pedestrian", "steps"}
EXACT_ACCURACY_M = 2
CONFIG_VERSION = "VITAP_CONFIG_V4_OSM_CALIBRATED"
STUB_WARN_M = 30.0

LAT0, LON0 = 16.493, 80.499
M_LAT = 111190.0
M_LON = 111320.0 * math.cos(math.radians(LAT0))


def to_xy(lat, lon):
    return ((lon - LON0) * M_LON, (lat - LAT0) * M_LAT)


def to_ll(x, y):
    return (LAT0 + y / M_LAT, LON0 + x / M_LON)


def dist_ll(a, b):
    ax, ay = to_xy(*a)
    bx, by = to_xy(*b)
    return math.hypot(ax - bx, ay - by)


# --------------------------------------------------------------------------- OSM
def load_extract():
    d = json.loads(EXTRACT.read_text(encoding="utf-8"))
    nodes = {int(k): tuple(v) for k, v in d["nodes"].items()}
    ways = {int(k): v for k, v in d["ways"].items()}
    return nodes, ways


def load_relations():
    d = json.loads(EXTRACT.read_text(encoding="utf-8"))
    return {int(k): v for k, v in d.get("relations", {}).items()}


def outer_way_id(rel):
    return next(m["ref"] for m in rel["members"] if m["role"] == "outer")


def relation_centroid(rel, ways, nodes):
    """Area-weighted centroid of (outer - inner) rings of a multipolygon building."""
    num_x = num_y = area = 0.0
    for m in rel["members"]:
        a, c = polygon_area_centroid(ways[m["ref"]], nodes)
        sign = 1.0 if m["role"] == "outer" else -1.0
        cx, cy = to_xy(*c)
        num_x += sign * a * cx
        num_y += sign * a * cy
        area += sign * a
    return to_ll(num_x / area, num_y / area)


def way_centroid(way, nodes):
    """Vertex-mean centroid (same method as the original OSM-derived config)."""
    pts = [nodes[n] for n in way["nodes"]]
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def polygon_area_centroid(way, nodes):
    pts = [to_xy(*nodes[n]) for n in way["nodes"]]
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cr = x0 * y1 - x1 * y0
        a += cr
        cx += (x0 + x1) * cr
        cy += (y0 + y1) * cr
    a *= 0.5
    return abs(a), to_ll(cx / (6 * a), cy / (6 * a))


def ring_wkt(way, nodes):
    return "(" + ", ".join(f"{nodes[n][0]:.7f} {nodes[n][1]:.7f}" for n in way["nodes"]) + ")"


# -------------------------------------------------------------------- calibration
def fit_affine(pairs):
    A = np.array([[px, py, 1.0] for (px, py), _ in pairs])
    Y = np.array([ll for _, ll in pairs])
    M, *_ = np.linalg.lstsq(A, Y, rcond=None)
    return M


def apply_affine(M, px, py):
    return tuple(float(v) for v in np.array([px, py, 1.0]) @ M)


def build_nodes(spec, osm_nodes, osm_ways, osm_rels=None):
    """-> {node_id: record} for every placed node, plus fit diagnostics."""
    recs = {}
    for nid, way_id in spec["exact"].items():
        lat, lon = way_centroid(osm_ways[way_id], osm_nodes)
        recs[nid] = dict(lat=round(lat, 7), lon=round(lon, 7), source=f"osm_way:{way_id}",
                         accuracy_m=EXACT_ACCURACY_M, kind="exact")

    rels = osm_rels if osm_rels is not None else load_relations()
    for nid, rel_id in spec.get("exact_relations", {}).items():
        lat, lon = relation_centroid(rels[rel_id], osm_ways, osm_nodes)
        recs[nid] = dict(lat=round(lat, 7), lon=round(lon, 7), source=f"osm_relation:{rel_id}",
                         accuracy_m=EXACT_ACCURACY_M, kind="exact", outline_way=outer_way_id(rels[rel_id]))

    for nid, way_ids in spec.get("exact_parking", {}).items():
        parts = [polygon_area_centroid(osm_ways[w], osm_nodes) for w in way_ids]
        total = sum(a for a, _ in parts)
        x = sum(a * to_xy(*c)[0] for a, c in parts) / total
        y = sum(a * to_xy(*c)[1] for a, c in parts) / total
        lat, lon = to_ll(x, y)
        recs[nid] = dict(lat=round(lat, 7), lon=round(lon, 7),
                         source="osm_way:" + "+".join(map(str, way_ids)),
                         accuracy_m=EXACT_ACCURACY_M, kind="exact",
                         boundary="MULTIPOLYGON(" + ", ".join(
                             "(" + ring_wkt(osm_ways[w], osm_nodes) + ")" for w in way_ids) + ")",
                         boundary_source="osm_way:" + "+".join(map(str, way_ids)))

    controls = [(tuple(c["pixel"]), (recs[nid]["lat"], recs[nid]["lon"]))
                for nid, c in spec["control_points"].items()]
    M = fit_affine(controls)
    loo = []
    for i, (px, true) in enumerate(controls):
        Mi = fit_affine(controls[:i] + controls[i + 1:])
        loo.append(dist_ll(apply_affine(Mi, *px), true))
    fit_res = [dist_ll(apply_affine(M, *px), true) for px, true in controls]
    diag = dict(n_controls=len(controls), fit_max_m=max(fit_res), loo_mean_m=float(np.mean(loo)),
                loo_max_m=max(loo), px_per_m_x=1 / (abs(M[0, 1]) * M_LON),
                px_per_m_y=1 / (abs(M[1, 0]) * M_LAT))
    if diag["loo_max_m"] > spec["max_control_loo_error_m"]:
        raise SystemExit(f"Calibration rejected: leave-one-out error {diag['loo_max_m']:.1f} m "
                         f"> {spec['max_control_loo_error_m']} m")

    # exact points that are visible in the image but not control points: independent check
    for nid, a in spec["approximate"].items():
        lat, lon = apply_affine(M, *a["pixel"])
        recs[nid] = dict(lat=round(lat, 6), lon=round(lon, 6), source="image_calibrated",
                         accuracy_m=spec["approximate_accuracy_m"], kind="approximate")
        if nid.endswith("-lot-sports") or "lot" in nid:
            recs[nid].setdefault("boundary_source", "placeholder")
    return recs, diag


def placeholder_polygon(lat, lon, half=0.0005):
    c = [(lat - half, lon - half), (lat + half, lon - half), (lat + half, lon + half),
         (lat - half, lon + half), (lat - half, lon - half)]
    return "POLYGON((" + ", ".join(f"{a:.6f} {b:.6f}" for a, b in c) + "))"


# ------------------------------------------------------------------ road geometry
def build_graph(ways, nodes, allowed):
    G = nx.Graph()
    for wid, w in ways.items():
        if w["tags"].get("highway") not in allowed:
            continue
        for a, b in zip(w["nodes"], w["nodes"][1:]):
            if a != b and a in nodes and b in nodes:
                G.add_edge(a, b, weight=dist_ll(nodes[a], nodes[b]), way=wid)
    return G


def nearest_segment(G, nodes, p):
    px, py = to_xy(*p)
    best = None
    for a, b, d in G.edges(data=True):
        ax, ay = to_xy(*nodes[a])
        bx, by = to_xy(*nodes[b])
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        qx, qy = ax + t * dx, ay + t * dy
        dd = math.hypot(px - qx, py - qy)
        if best is None or dd < best[0]:
            best = (dd, a, b, t, to_ll(qx, qy), d["way"], math.sqrt(L2))
    return best  # (stub_m, a, b, t, proj_ll, way, seg_len)


def route(G, nodes, p_start, p_end):
    s = nearest_segment(G, nodes, p_start)
    e = nearest_segment(G, nodes, p_end)
    H = G.copy()
    for tag, seg in (("S", s), ("E", e)):
        _, a, b, t, _, _, L = seg
        H.add_edge(tag, a, weight=t * L, way=seg[5])
        H.add_edge(tag, b, weight=(1 - t) * L, way=seg[5])
    if {s[1], s[2]} == {e[1], e[2]}:
        ts = s[3] if s[1] == e[1] else 1 - s[3]
        H.add_edge("S", "E", weight=abs(ts - e[3]) * s[6], way=s[5])
    try:
        path = nx.shortest_path(H, "S", "E", weight="weight")
    except nx.NetworkXNoPath:
        return None
    pts, ways_used, length = [], set(), 0.0
    for i, n in enumerate(path):
        pts.append(s[4] if n == "S" else e[4] if n == "E" else nodes[n])
        if i:
            ways_used.add(H.edges[path[i - 1], n]["way"])
            length += H.edges[path[i - 1], n]["weight"]
    return dict(points=pts, osm_length=length, stub_start=s[0], stub_end=e[0], ways=sorted(ways_used))


def building_entrance(way, graph, nodes, step_m=1.5):
    """Point on a building's outline closest to the walkable network, and its distance to it.

    OSM footways usually run up to a building's wall, not to its centroid, so a walk path
    should end at the wall (entrance side) and only then step inside to the node."""
    pts = [nodes[n] for n in way["nodes"]]
    best = None
    for a, b in zip(pts, pts[1:]):
        k = max(1, int(dist_ll(a, b) / step_m))
        for i in range(k + 1):
            p = (a[0] + (b[0] - a[0]) * i / k, a[1] + (b[1] - a[1]) * i / k)
            d = nearest_segment(graph, nodes, p)[0]
            if best is None or d < best[0]:
                best = (d, p)
    return best[1]


def add_entrances(recs, spec, ways, nodes, walk_graph):
    outlines = dict(spec["exact"])
    outlines.update({nid: recs[nid]["outline_way"] for nid in spec.get("exact_relations", {})})
    for nid, way_id in outlines.items():
        e = building_entrance(ways[way_id], walk_graph, nodes)
        recs[nid]["entrance"] = (round(e[0], 7), round(e[1], 7))


def road_geometry(road, recs, graphs, nodes):
    mode = "drive" if road["is_driveable"] else "walk"
    ends = []
    for nid in (road["start_node_id"], road["end_node_id"]):
        node = (recs[nid]["lat"], recs[nid]["lon"])
        ent = recs[nid].get("entrance") if mode == "walk" else None
        ends.append((node, ent))
    (n0, e0), (n1, e1) = ends
    r = route(graphs[mode], nodes, e0 or n0, e1 or n1)
    if r is None:
        return None
    poly = [n0] + ([e0] if e0 else []) + r["points"] + ([e1] if e1 else []) + [n1]
    out = []
    for p in poly:  # drop consecutive duplicates (< 0.2 m)
        if not out or dist_ll(out[-1], p) > 0.2:
            out.append(p)
    if out[-1] != n1:
        out[-1] = n1
    r["polyline"] = out
    r["geom_length"] = sum(dist_ll(a, b) for a, b in zip(out, out[1:]))
    r["mode"] = mode
    # Length of each end that is NOT on a mapped road: building interior + off-road stub.
    r["access_start_m"] = round((dist_ll(n0, e0) if e0 else 0.0) + r["stub_start"], 1)
    r["access_end_m"] = round((dist_ll(n1, e1) if e1 else 0.0) + r["stub_end"], 1)
    return r


# --------------------------------------------------------------- YAML text surgery
ITEM = re.compile(r"^  - (gate_id|parking_lot_id|destination_id|road_id|from_node_id): (.+)$")


def split_blocks(lines):
    starts = [i for i, l in enumerate(lines) if ITEM.match(l)]
    blocks = []
    for s in starts:
        a = s
        while a > 0 and re.match(r"^  #", lines[a - 1]):
            a -= 1
        e = s + 1
        while e < len(lines) and lines[e].strip() and not re.match(r"^(  - |  #|#|\S)", lines[e]):
            e += 1
        blocks.append((a, s, e))
    return blocks


def block_value(lines, s, key):
    for l in lines[s:]:
        m = re.match(rf"^    {key}: (.+)$", l)
        if m:
            return m.group(1).strip().strip('"')
        if re.match(r"^  - |^\S", l) and l is not lines[s]:
            break
    return None


def rewrite_node(body, name, rec, is_lot):
    kept = [l for l in body if not re.match(r"^    (coordinate_source|coordinate_accuracy_m|boundary_source):", l)]
    if not any(re.match(r"^    latitude:", l) for l in kept):
        # previously unplaced node: add coordinate lines (values are filled just below)
        at = next(i for i, l in enumerate(kept) if re.match(r"^    name:", l)) + 1
        kept[at:at] = ["    latitude: 0", "    longitude: 0"]
    out = []
    note = ("exact: OpenStreetMap " + rec["source"].split(":")[1] if rec["kind"] == "exact"
            else f"APPROXIMATE (+/-{rec['accuracy_m']} m): calibrated from reference map image")
    out.append(f"  # {name} - {note}")
    for l in kept:
        if re.match(r"^    latitude:", l):
            out.append(f"    latitude: {rec['lat']}")
        elif re.match(r"^    longitude:", l):
            out.append(f"    longitude: {rec['lon']}")
            out.append(f'    coordinate_source: "{rec["source"]}"')
            out.append(f"    coordinate_accuracy_m: {rec['accuracy_m']}")
        elif is_lot and re.match(r"^    boundary_polygon:", l):
            poly = rec.get("boundary") or placeholder_polygon(rec["lat"], rec["lon"])
            out.append(f'    boundary_polygon: "{poly}"')
            out.append(f'    boundary_source: "{rec.get("boundary_source", "placeholder")}"')
        else:
            out.append(l)
    return out


WALK_S_PER_M = 0.8  # existing walk roads: expected_travel_time_seconds = 0.8 * length_meters


def derived_weights(geom_length, drive):
    length = round(geom_length)
    return length, round(length / 5.0) if drive else round(length * WALK_S_PER_M)


def set_weights(body, length, seconds, edge):
    out = []
    for l in body:
        if edge and l.startswith("    weight_time_seconds:"):
            l = f"    weight_time_seconds: {seconds}"
        elif edge and l.startswith("    weight_distance_meters:"):
            l = f"    weight_distance_meters: {length}"
        elif not edge and l.startswith("    length_meters:"):
            l = f"    length_meters: {length}"
        elif not edge and l.startswith("    expected_travel_time_seconds:"):
            l = f"    expected_travel_time_seconds: {seconds}"
        out.append(l)
    return out


def rewrite_unplaced(body, name, reason):
    out = [f"  # {name} - NOT PLACED: {reason} (kept in graph/DB, not drawn)"]
    for l in body:
        if re.match(r"^    (latitude|longitude|coordinate_source|coordinate_accuracy_m):", l):
            continue
        out.append(l)
        if re.match(r"^    name:", l):
            out.append('    coordinate_source: "unplaced"')
    return out


def rewrite_road(body, geom_pts, access=None):
    out, i = [], 0
    body = [l for l in body if not re.match(r"^    (geometry_source|access_start_m|access_end_m):", l)]
    while i < len(body):
        l = body[i]
        if l.startswith("    geometry:") and not geom_pts:
            out.append('    geometry_source: "unplaced"')
            out.append("    geometry: []")
            i += 1
            while i < len(body) and body[i].startswith("      - {"):
                i += 1
            continue
        if l.startswith("    geometry:"):
            out.append('    geometry_source: "osm_snapped"')
            if access:
                out.append(f"    access_start_m: {access[0]}")
                out.append(f"    access_end_m: {access[1]}")
            out.append("    geometry:")
            for lat, lon in geom_pts:
                out.append(f"      - {{ lat: {lat:.7f}, lng: {lon:.7f} }}")
            i += 1
            while i < len(body) and body[i].startswith("      - {"):
                i += 1
            continue
        out.append(l)
        i += 1
    return out


HEADER = f"""# VIT-AP Campus Configuration v4.0 - OSM-CALIBRATED
# =========================================================
# GENERATED coordinates/geometry: edit configs/campus/vitap_calibration.yaml and re-run
#   python scripts/calibrate_campus_from_osm.py --apply
# Do not hand-edit latitude/longitude/geometry below.
#
# Every placed node carries its provenance:
#   coordinate_source "osm_way:<id>"    EXACT: centroid of an OpenStreetMap way (ODbL)
#   coordinate_source "image_calibrated" APPROXIMATE (+/-25 m): read off the reference map
#                                        image through a transform fitted to OSM points.
#                                        NOT surveyed. Replace with GPS points when available.
#   boundary_source   "osm_way:<id>" real footprint | "placeholder" 100 m box, NOT a real boundary
#   geometry_source   "osm_snapped"      road polyline follows real OSM roads between its nodes
#
# length_meters / expected_travel_time_seconds / edge weights are UNCHANGED from v3 so that
# committed experiment results stay reproducible. They are NOT recalibrated to the geometry
# below; see docs/road_length_discrepancies.md.
#
# REMOVED on request: AP-2 (and its roads/edges). See `removed` in configs/campus/vitap_calibration.yaml.
# Coordinate convention: latitude/longitude here and in the DB; boundary_polygon is
# lat-first (not standard WKT lng-first).
# =========================================================

"""


RULE = "# " + "=" * 53

BANNERS = {
    "gates:": ("# GATES", [
        "# GATES - APPROXIMATE (image-calibrated, +/-25 m; OSM has no gate nodes)",
    ]),
    "parking_lots:": ("# PARKING LOTS", [
        "# PARKING LOTS - Overflow: exact OSM footprint. Others: APPROXIMATE centre (+/-25 m),",
        '# boundary_source "placeholder" (100 m box, not a real boundary).',
    ]),
    "destinations:": ("# DESTINATIONS", [
        "# DESTINATIONS - exact (OSM) except Library, Sports Complex, MH-4, LH-2 (approximate).",
        "# AP-2 is intentionally NOT configured (removed on request). LH-3 is new and excluded from",
        "# seeded simulation demand (include_in_simulation: false).",
    ]),
    "roads:": ("# ROADS", [
        "# ROADS - geometry snapped to real OSM roads (geometry_source: osm_snapped).",
        "# length_meters / expected_travel_time_seconds are the ORIGINAL v3 values, NOT derived",
        "# from this geometry (see docs/road_length_discrepancies.md).",
        "# Roads to a node with no coordinates would carry geometry [] (geometry_source: unplaced).",
    ]),
}


def normalise_banners(text):
    """Replace each section banner (idempotent) so it describes the calibrated data."""
    for key, (marker, body) in BANNERS.items():
        start = text.index(RULE + "\n" + marker)
        end = text.index("\n" + key + "\n", start) + 1
        text = text[:start] + "\n".join([RULE, *body, RULE]) + "\n" + text[end:]
    return text


def apply_to_text(text, recs, geoms, spec, derived):
    lines = text.splitlines()
    unconf = spec["unconfigured"]
    removed = set(spec.get("removed", {}))

    out, cursor = list(), 0
    for a, s, e in split_blocks(lines):
        out.extend(lines[cursor:a])
        key, val = ITEM.match(lines[s]).groups()
        val = val.strip()
        body = lines[s:e]
        gone = (
            (key == "destination_id" and val in removed)
            or (key == "road_id" and (block_value(lines, s, "start_node_id") in removed
                                      or block_value(lines, s, "end_node_id") in removed))
            or (key == "from_node_id" and (val in removed or block_value(lines, s, "to_node_id") in removed))
        )
        if gone:  # drop the block (and the blank line after it)
            cursor = e + 1 if e < len(lines) and not lines[e].strip() else e
            continue
        if key == "destination_id" and val in unconf:
            out.extend(rewrite_unplaced(body, block_value(lines, s, "name"), unconf[val]))
        elif key in ("gate_id", "parking_lot_id", "destination_id") and val in recs:
            out.extend(rewrite_node(body, block_value(lines, s, "name"), recs[val], key == "parking_lot_id"))
        elif key == "road_id" and val in geoms:
            out.extend(lines[a:s])  # keep the road's own comment lines
            if val in derived:
                body = set_weights(body, *derived[val], edge=False)
            out.extend(rewrite_road(body, geoms[val]["polyline"],
                                    (geoms[val]["access_start_m"], geoms[val]["access_end_m"])))
        elif key == "road_id" and (block_value(lines, s, "start_node_id") in unconf
                                   or block_value(lines, s, "end_node_id") in unconf):
            out.extend(lines[a:s])
            out.extend(rewrite_road(body, []))
        elif key == "from_node_id" and block_value(lines, s, "road_id") in derived:
            out.extend(lines[a:s])
            out.extend(set_weights(body, *derived[block_value(lines, s, "road_id")], edge=True))
        else:
            out.extend(lines[a:e])
        cursor = e
    out.extend(lines[cursor:])
    text = "\n".join(out) + "\n"
    _, _, rest = text.partition("\ncampus:")
    text = HEADER + "campus:" + rest
    text = re.sub(r"configuration_version: \S+", f"configuration_version: {CONFIG_VERSION}", text, count=1)
    return normalise_banners(text)


# ------------------------------------------------------------------------ reports
def haversine_len(points):
    return sum(dist_ll(a, b) for a, b in zip(points, points[1:]))


def coverage_summary(cfg, recs, graphs, nodes):
    items = {}
    for sec, k in (("gates", "gate_id"), ("parking_lots", "parking_lot_id"), ("destinations", "destination_id")):
        for x in cfg[sec]:
            items[x[k]] = (x["name"], sec)
    out = {"nodes": [], "single_lot": [], "single_gate": [], "names": {k: v[0] for k, v in items.items()}}
    for nid, (name, sec) in items.items():
        if nid not in recs:
            continue
        p = (recs[nid]["lat"], recs[nid]["lon"])
        ref = recs[nid].get("entrance") or p  # buildings are measured from their wall
        out["nodes"].append((name, sec, nearest_segment(graphs["walk"], nodes, ref)[0],
                             nearest_segment(graphs["drive"], nodes, p)[0], recs[nid].get("entrance")))
    walk, drive = {}, {}
    for r in cfg["roads"]:
        (drive if r["is_driveable"] else walk).setdefault(r["end_node_id"], set()).add(r["start_node_id"])
    for nid, (name, sec) in items.items():
        if sec == "destinations" and len(walk.get(nid, ())) == 1:
            out["single_lot"].append((name, items[next(iter(walk[nid]))][0]))
        if sec == "parking_lots" and len(drive.get(nid, ())) == 1:
            out["single_gate"].append(f"{name} (only from {items[next(iter(drive[nid]))][0]})")
    return out


def write_reports(docs_dir, before_cfg, recs, geoms, diag, spec, coverage):
    docs_dir.mkdir(parents=True, exist_ok=True)
    removed_roads = {r["road_id"] for r in before_cfg["roads"]} - set(geoms)  # roads with an unplaced end
    nodes_before = {}
    for sec, idk in (("gates", "gate_id"), ("parking_lots", "parking_lot_id"), ("destinations", "destination_id")):
        for x in before_cfg[sec]:
            nodes_before[x[idk]] = (x["name"], x["latitude"], x["longitude"])
    L = ["# Map calibration report", "",
         "Generated by `scripts/calibrate_campus_from_osm.py` (spec: `configs/campus/vitap_calibration.yaml`).",
         "Data (c) OpenStreetMap contributors, ODbL 1.0.", "",
         "## Method", "",
         "* **Exact** positions: centroid of the OSM way. Never overwritten by an estimate.",
         f"* **Approximate** positions: pixel positions read from the reference image, converted with an affine "
         f"transform fitted to {diag['n_controls']} exact OSM control buildings "
         f"(fit max {diag['fit_max_m']:.1f} m, leave-one-out mean {diag['loo_mean_m']:.1f} m / "
         f"max {diag['loo_max_m']:.1f} m, scale ~{diag['px_per_m_x']:.2f} px/m). "
         f"The control fit is accurate, but the pixel readings and the image author's own placement of "
         f"lots/gates are not verifiable, so these points are treated as **+/-{spec['approximate_accuracy_m']} m**. "
         "They are not surveyed.",
         "* **Roads**: shortest path along real OSM roads (vehicle roads for drivable links; vehicle roads and "
         "footways for walk links) between the two end nodes. The first/last point is the node itself, so a short "
         "off-road stub joins nodes that are not on a mapped road.",
         "* **Unchanged on purpose**: `length_meters`, `expected_travel_time_seconds` and edge weights of every "
         "pre-existing road. Routing costs are **not** geographically recalibrated. Only roads added later (LH-3) "
         "have weights derived from their geometry, because no earlier value exists.", "",
         "## Corrected locations", "",
         "| Location | Before (lat, lng) | After (lat, lng) | Moved | Source | Accuracy |", "|---|---|---|---|---|---|"]
    for nid, r in recs.items():
        src = (r["source"].replace("osm_way:", "OSM way ").replace("osm_relation:", "OSM relation ")
               if r["kind"] == "exact" else "image-calibrated")
        acc = "exact (OSM)" if r["kind"] == "exact" else "+/-%d m" % r["accuracy_m"]
        if nid in nodes_before:
            nm, la, lo = nodes_before[nid]
            L.append(f"| {nm} | {la:.6f}, {lo:.6f} | {r['lat']:.6f}, {r['lon']:.6f} | "
                     f"{dist_ll((la, lo), (r['lat'], r['lon'])):.0f} m | {src} | {acc} |")
        else:  # destination added after the pre-calibration config
            nm = coverage["names"].get(nid, nid)
            L.append(f"| {nm} (new) | - | {r['lat']:.6f}, {r['lon']:.6f} | - | {src} | {acc} |")
    if spec["unconfigured"]:
        L += ["", "## Unplaced (no reference coordinates)", "",
              "Kept in the routing graph and database with no coordinates; not drawn.", ""]
        for nid, why in spec["unconfigured"].items():
            L.append(f"* **{nodes_before[nid][0]}** (`{nid}`): {why}.")
    if spec.get("removed"):
        L += ["", "## Removed destinations", "",
              "Removed from the config, routing graph, database, API and UI. The seeded simulation draws vehicle "
              "destinations from the destinations table, so removing one **shifts every seeded result** relative to "
              "the committed experiments (their files are untouched, but re-running them gives different numbers).", ""]
        for nid, why in spec["removed"].items():
            roads = sorted(r["road_id"] for r in before_cfg["roads"] if nid in (r["start_node_id"], r["end_node_id"]))
            L.append(f"* **{nodes_before[nid][0]}** (`{nid}`): {why}. Roads removed with it: {', '.join(roads) or 'none'}.")
    L += ["", "## Parking boundaries", "",
          "* Overflow Parking: real OSM footprints (two ways either side of the main avenue).",
          "* All other lots: `boundary_source: placeholder` (100 m box around the approximate centre). "
          "**Not a real boundary**; the UI does not draw it as one.", ""]
    L += ["## Path coverage", "",
          "How far each node is from a mapped OSM road. Where OSM has no path between a node and the road "
          "network, a dotted *access link* is drawn (`access_start_m` / `access_end_m` per road, which also "
          "include the stretch inside a building); no path is invented. For buildings the path now ends at "
          "the building outline (entrance side), not the centroid.", "",
          "| Node | Type | To nearest walkable road | To nearest drivable road | Note |", "|---|---|---|---|---|"]
    for name, sec, w, d, ent in coverage["nodes"]:
        note = ("approximate position in open ground, no mapped road nearby" if w > 30 and sec == "parking_lots"
                else "path ends at the building outline" if ent is not None else "")
        L.append(f"| {name} | {sec} | {w:.0f} m | {d:.0f} m | {note} |")
    L += ["", "Destinations with a walk link from only ONE parking lot (existing routing topology, unchanged: "
          "adding links changes routing costs):", ""]
    for name, lot in coverage["single_lot"]:
        L.append(f"* {name}: {lot}")
    L += ["", "Parking lots with a drive link from only ONE gate: "
          + (", ".join(coverage["single_gate"]) or "none") + ".", ""]
    (docs_dir / "map_calibration.md").write_text("\n".join(L), encoding="utf-8")

    # road discrepancy report
    before_roads = {r["road_id"]: r for r in before_cfg["roads"]}
    rows, orig_bad = [], []
    for rid, rb in before_roads.items():  # every road in the pre-calibration config
        old_len = haversine_len([(p["lat"], p["lng"]) for p in rb["geometry"]])
        decl = rb["length_meters"]
        g = geoms.get(rid)  # None: road removed with an unconfigured destination
        row = dict(rid=rid, decl=decl, old=old_len, new=g["geom_length"] if g else None,
                   stub=max(g["stub_start"], g["stub_end"]) if g else None, mode=g["mode"] if g else None)
        if g:
            rows.append(row)
        if not (0.9 <= decl / old_len <= 2.5):
            orig_bad.append(row)
    new_roads = []
    for rid, g in geoms.items():  # roads added after the pre-calibration config (weights derived from geometry)
        if rid not in before_roads and g.get("derived"):
            row = dict(rid=rid, decl=g["derived"][0], old=None, new=g["geom_length"],
                       stub=max(g["stub_start"], g["stub_end"]), mode=g["mode"])
            rows.append(row)
            new_roads.append(rid)
    D = ["# Road length discrepancies", "",
         "`length_meters` / `expected_travel_time_seconds` are **unchanged** from the committed config. They were "
         "never derived from geometry. This report documents how far apart they are. **Nothing here has been "
         "recalibrated**; fixing it changes routing costs and requires re-running the experiments.", "",
         "Ratio = declared length / geometry length (1.0 would be consistent).", "",
         f"## A. The {len(orig_bad)} original discrepancies (declared vs the old hand-drawn geometry, ratio outside 0.9-2.5)", "",
         "These were present before this calibration. They are documented here, not fixed.", "",
         "| Road | Declared m | Old geometry m | Old ratio | New OSM geometry m | New ratio |", "|---|---|---|---|---|---|"]
    for r in sorted(orig_bad, key=lambda r: r["decl"] / r["old"]):
        if r["new"] is None:
            D.append(f"| {r['rid']} | {r['decl']} | {r['old']:.0f} | {r['decl']/r['old']:.2f} | "
                     "removed (destination removed) | n/a |")
        else:
            D.append(f"| {r['rid']} | {r['decl']} | {r['old']:.0f} | {r['decl']/r['old']:.2f} | "
                     f"{r['new']:.0f} | {r['decl']/r['new']:.2f} |")
    D += ["", f"## B. All {len(rows)} drawn roads against the new OSM geometry", "",
          "| Road | Mode | Declared m | New geometry m | Ratio | Longest open-ground gap (m) |", "|---|---|---|---|---|---|"]
    for r in rows:
        flag = " (!)" if r["stub"] > STUB_WARN_M else ""
        D.append(f"| {r['rid']} | {r['mode']} | {r['decl']} | {r['new']:.0f} | {r['decl']/r['new']:.2f} | {r['stub']:.0f}{flag} |")
    if new_roads:
        D += ["", "New roads (no earlier value exists): " + ", ".join(new_roads) + ". Their length/time/edge weights are "
              "derived from the OSM geometry (0.8 s per metre, the convention of the existing walk roads), so their "
              "ratio is 1.00 by construction. They are the only weights not carried over from v3."]
    D += ["", f"(!) = more than {STUB_WARN_M:.0f} m of open ground between a node (or building wall) and the nearest mapped road; expected for approximate nodes. Building interiors are not counted as gaps.", ""]
    (docs_dir / "road_length_discrepancies.md").write_text("\n".join(D), encoding="utf-8")
    return rows, orig_bad


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="rewrite configs/campus/vitap.yaml")
    ap.add_argument("--report-only", action="store_true", help="regenerate the docs without touching the config")
    ap.add_argument("--before", help="pre-calibration vitap.yaml (for the before/after reports)")
    ap.add_argument("--docs", help="directory for the generated reports")
    args = ap.parse_args()

    spec = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    nodes, ways = load_extract()
    recs, diag = build_nodes(spec, nodes, ways)
    print("calibration fit:", {k: round(v, 2) for k, v in diag.items()})

    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    unconf = set(spec["unconfigured"])
    removed = set(spec.get("removed", {}))
    graphs = {"drive": build_graph(ways, nodes, DRIVE_HW), "walk": build_graph(ways, nodes, WALK_HW)}

    add_entrances(recs, spec, ways, nodes, graphs["walk"])
    placed = {x[k] for sec, k in (("gates", "gate_id"), ("parking_lots", "parking_lot_id"),
                                  ("destinations", "destination_id")) for x in cfg[sec]} - unconf - removed
    unplaced = placed - set(recs)
    if unplaced:
        raise SystemExit(f"Nodes with no coordinate source in the spec: {sorted(unplaced)}")

    geoms, failures = {}, []
    for r in cfg["roads"]:
        if {r["start_node_id"], r["end_node_id"]} & (unconf | removed):
            continue
        g = road_geometry(r, recs, graphs, nodes)
        (geoms.__setitem__(r["road_id"], g) if g else failures.append(r["road_id"]))
    if failures:
        raise SystemExit(f"No OSM route (road would have to be invented) for: {failures}")
    far = [(rid, max(g["stub_start"], g["stub_end"])) for rid, g in geoms.items()
           if max(g["stub_start"], g["stub_end"]) > STUB_WARN_M]
    oneway = [rid for rid, g in geoms.items() if g["mode"] == "drive"
              and any(ways[w]["tags"].get("oneway") for w in g["ways"])]
    print(f"{len(geoms)} roads snapped; {len(far)} with an open-ground gap > {STUB_WARN_M:.0f} m; "
          f"drive roads using a one-way OSM way: {oneway}")

    derived = {}
    for r in cfg["roads"]:
        if r.get("weights_source") == "osm_geometry" and r["road_id"] in geoms:
            derived[r["road_id"]] = derived_weights(geoms[r["road_id"]]["geom_length"], r["is_driveable"])
            geoms[r["road_id"]]["derived"] = derived[r["road_id"]]
    if args.apply:
        text = apply_to_text(CONFIG.read_text(encoding="utf-8"), recs, geoms, spec, derived)
        CONFIG.write_text(text, encoding="utf-8", newline="\n")
        print(f"Rewrote {CONFIG.name}")
    if (args.apply or args.report_only) and args.before and args.docs:
        before_cfg = yaml.safe_load(Path(args.before).read_text(encoding="utf-8"))
        write_reports(Path(args.docs), before_cfg, recs, geoms, diag, spec,
                      coverage_summary(cfg, recs, graphs, nodes))
        print("Reports written to", args.docs)


if __name__ == "__main__":
    main()
