"""Coordinate integrity for the VIT-AP map.

Source of truth chain (see docs/map_calibration.md):
    OpenStreetMap extract + configs/campus/vitap_calibration.yaml
        --scripts/calibrate_campus_from_osm.py--> configs/campus/vitap.yaml
        --loader--> SQLite --/campus--> UI

These tests pin each link so markers, roads and routes cannot drift apart again.
They prove consistency with OpenStreetMap, NOT survey-grade accuracy: nodes whose
coordinate_source is "image_calibrated" are approximate (+/-25 m) by design.
"""

import json
import math
import re
import sqlite3
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import digital_twin.api.app as api
from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import calibrate_campus_from_osm as calib  # noqa: E402

CFG = yaml.safe_load((ROOT / "configs" / "campus" / "vitap.yaml").read_text(encoding="utf-8"))
SPEC = yaml.safe_load((ROOT / "configs" / "campus" / "vitap_calibration.yaml").read_text(encoding="utf-8"))
BASELINE = json.loads((ROOT / "tests" / "fixtures" / "road_weights_baseline.json").read_text(encoding="utf-8"))
OSM_NODES, OSM_WAYS = calib.load_extract()
UNCONFIGURED = set(SPEC["unconfigured"])          # unplaced: no coordinates, still in the graph
REMOVED = set(SPEC["removed"])                    # removed from the campus entirely
# Baseline (pre-calibration) roads/edges that touched a removed destination are gone by design.
REMOVED_ROADS = {rid for rid, b in BASELINE["roads"].items() if REMOVED & {b["start"], b["end"]}}
BASELINE_DEMAND = [d for d in BASELINE["destination_ids"] if d not in REMOVED]


def _haversine_m(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


OSM_RELS = calib.load_relations()
NEW_ROAD_IDS = {"vitap-road-sports-lot-to-lh3", "vitap-road-hostel-lot-to-lh3"}
NEW_DEST_IDS = {"vitap-osm-lh3-001"}


def _building_way(nid):
    """OSM way whose outline is the building wall for an exact building node, else None."""
    if nid in SPEC["exact"]:
        return SPEC["exact"][nid]
    if nid in SPEC.get("exact_relations", {}):
        return calib.outer_way_id(OSM_RELS[SPEC["exact_relations"][nid]])
    return None


def _is_exact(source):
    return bool(source) and source.startswith(("osm_way:", "osm_relation:"))


def _items():
    """Every placed node: id -> config dict (gate / lot / destination)."""
    out = {}
    for sec, key in (("gates", "gate_id"), ("parking_lots", "parking_lot_id"), ("destinations", "destination_id")):
        for x in CFG[sec]:
            out[x[key]] = x
    return out


def _nodes():
    """Placed nodes only (unplaced ones have no coordinates by design)."""
    return {k: (v["latitude"], v["longitude"]) for k, v in _items().items() if "latitude" in v}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "coord_test.db")
    monkeypatch.setattr(api, "CAMPUS_YAML", ROOT / "configs" / "campus" / "vitap.yaml")
    with TestClient(api.app) as c:
        yield c


# ---------------------------------------------------------------- basic geometry
def test_no_latitude_longitude_inversion():
    nodes = _nodes()
    lats = [v[0] for v in nodes.values()]
    lngs = [v[1] for v in nodes.values()]
    assert max(lats) - min(lats) < 0.02, "latitude spread too large: lat/lng swapped?"
    assert max(lngs) - min(lngs) < 0.02, "longitude spread too large: lat/lng swapped?"
    assert all(la < lo for la, lo in nodes.values()), "expected lat < lng for this campus"


def test_no_duplicate_or_stacked_nodes():
    nodes = list(_nodes().items())
    for i, (id_a, a) in enumerate(nodes):
        for id_b, b in nodes[i + 1:]:
            assert _haversine_m(a, b) > 10, f"{id_a} and {id_b} are stacked on one point"


def test_each_lot_lies_within_its_boundary_extent():
    # boundary_polygon is lat-first "POLYGON((lat lng, ...))" / "MULTIPOLYGON(...)".
    for p in CFG["parking_lots"]:
        pts = [tuple(map(float, m)) for m in re.findall(r"([\d.]+)\s+([\d.]+)", p["boundary_polygon"])]
        assert min(q[0] for q in pts) <= p["latitude"] <= max(q[0] for q in pts), p["parking_lot_id"]
        assert min(q[1] for q in pts) <= p["longitude"] <= max(q[1] for q in pts), p["parking_lot_id"]


def test_road_geometry_starts_and_ends_on_its_nodes():
    nodes = _nodes()
    for r in CFG["roads"]:
        if r["geometry_source"] == "unplaced":
            continue
        g = r["geometry"]
        assert len(g) >= 3, r["road_id"]
        assert _haversine_m((g[0]["lat"], g[0]["lng"]), nodes[r["start_node_id"]]) < 1, r["road_id"]
        assert _haversine_m((g[-1]["lat"], g[-1]["lng"]), nodes[r["end_node_id"]]) < 1, r["road_id"]


# ------------------------------------------------------------------ provenance
def test_every_placed_node_declares_its_provenance():
    for nid, x in _items().items():
        assert x.get("coordinate_source"), nid
        if nid in UNCONFIGURED:
            assert x["coordinate_source"] == "unplaced" and "latitude" not in x and "longitude" not in x, nid
            continue
        assert x.get("coordinate_accuracy_m"), nid
        if _is_exact(x["coordinate_source"]):
            assert x["coordinate_accuracy_m"] <= 5, f"{nid}: exact node with loose accuracy"
        else:
            assert x["coordinate_source"] == "image_calibrated", nid
            assert 20 <= x["coordinate_accuracy_m"] <= 25, nid


def test_exact_nodes_equal_their_osm_source_and_were_not_overwritten():
    items = _items()
    for nid, way_id in SPEC["exact"].items():
        cfg = items[nid]
        assert cfg["coordinate_source"] == f"osm_way:{way_id}", f"{nid} overwritten by a non-OSM source"
        lat, lon = calib.way_centroid(OSM_WAYS[way_id], OSM_NODES)
        assert _haversine_m((cfg["latitude"], cfg["longitude"]), (lat, lon)) < 0.5, nid
    for nid, rel_id in SPEC["exact_relations"].items():
        cfg = items[nid]
        assert cfg["coordinate_source"] == f"osm_relation:{rel_id}", f"{nid} overwritten by a non-OSM source"
        lat, lon = calib.relation_centroid(OSM_RELS[rel_id], OSM_WAYS, OSM_NODES)
        assert _haversine_m((cfg["latitude"], cfg["longitude"]), (lat, lon)) < 0.5, nid
        assert OSM_RELS[rel_id]["tags"]["name"] == cfg["name"], f"relation {rel_id} is not {cfg['name']}"
    for nid, way_ids in SPEC["exact_parking"].items():
        assert items[nid]["coordinate_source"] == "osm_way:" + "+".join(map(str, way_ids))
        assert items[nid]["boundary_source"] == items[nid]["coordinate_source"]


def test_config_is_in_sync_with_calibration_spec():
    """vitap.yaml must be reproducible from spec + OSM extract (no hand-edited coordinates)."""
    recs, diag = calib.build_nodes(SPEC, OSM_NODES, OSM_WAYS)
    assert diag["loo_max_m"] < 5
    items = _items()
    for nid, rec in recs.items():
        assert (items[nid]["latitude"], items[nid]["longitude"]) == (rec["lat"], rec["lon"]), nid
    assert set(recs) == set(items) - UNCONFIGURED, "config has nodes the calibration spec does not account for"


def test_removed_destinations_are_gone_everywhere(tmp_path):
    """A removed destination (AP-2) must not survive in the config, graph, DB or API."""
    assert REMOVED, "spec should list the removed destinations"
    for nid in REMOVED:
        assert nid not in _items()
        assert all(nid not in (r["start_node_id"], r["end_node_id"]) for r in CFG["roads"])
        assert all(nid not in (e["from_node_id"], e["to_node_id"]) for e in CFG["edges"])
        assert all(nid not in d.get("nearest_gate_ids", []) + d.get("nearest_parking_lot_ids", [])
                   for d in CFG["destinations"])
    assert REMOVED_ROADS, "baseline should show which roads went with the removed destination"
    assert not (REMOVED_ROADS & {r["road_id"] for r in CFG["roads"]})


# ---------------------------------------------------------------- road alignment
def _osm_segments(allowed):
    segs = []
    for w in OSM_WAYS.values():
        if w["tags"].get("highway") in allowed:
            for a, b in zip(w["nodes"], w["nodes"][1:]):
                segs.append((OSM_NODES[a], OSM_NODES[b]))
    return segs


def _dist_to_segment_m(p, a, b):
    px, py = calib.to_xy(*p)
    ax, ay = calib.to_xy(*a)
    bx, by = calib.to_xy(*b)
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _outline_segments(way_id):
    pts = [OSM_NODES[n] for n in OSM_WAYS[way_id]["nodes"]]
    return list(zip(pts, pts[1:]))


def test_every_road_follows_real_osm_roads():
    """All points between the two end nodes lie on an OSM road of the right class, or (walk roads
    only) on the outline of the OSM building at that end: the path ends at the building wall."""
    drive, walk = _osm_segments(calib.DRIVE_HW), _osm_segments(calib.WALK_HW)
    for r in CFG["roads"]:
        if r.get("geometry_source") == "unplaced":
            continue
        assert r.get("geometry_source") == "osm_snapped", r["road_id"]
        segs = drive if r["is_driveable"] else walk
        outline = []
        if not r["is_driveable"]:
            for end in ("start_node_id", "end_node_id"):
                if _building_way(r[end]):
                    outline += _outline_segments(_building_way(r[end]))
        for pt in r["geometry"][1:-1]:
            p = (pt["lat"], pt["lng"])
            d = min(_dist_to_segment_m(p, a, b) for a, b in segs + outline)
            assert d < 0.5, f"{r['road_id']}: point {pt} is {d:.1f} m off any OSM road/building wall"


def test_access_links_are_declared_and_consistent():
    """Each drawn road states how much of each end is NOT on a mapped road."""
    for r in CFG["roads"]:
        if r["geometry_source"] == "unplaced":
            assert "access_start_m" not in r
            continue
        pts = [(p["lat"], p["lng"]) for p in r["geometry"]]
        total = sum(_haversine_m(a, b) for a, b in zip(pts, pts[1:]))
        assert r["access_start_m"] >= 0 and r["access_end_m"] >= 0, r["road_id"]
        assert r["access_start_m"] + r["access_end_m"] <= total + 1, r["road_id"]


def test_building_paths_end_at_the_wall_not_the_centroid():
    """Walk roads to an OSM building must reach its outline: the old centroid-to-road line crossed the building."""
    for r in CFG["roads"]:
        way = _building_way(r["end_node_id"])
        if r["geometry_source"] != "osm_snapped" or not way or r["is_driveable"]:
            continue
        entrance = r["geometry"][-2]
        d = min(_dist_to_segment_m((entrance["lat"], entrance["lng"]), a, b) for a, b in _outline_segments(way))
        assert d < 0.5, f"{r['road_id']}: last mapped point is {d:.1f} m from {r['end_node_id']}'s wall"


def test_drive_roads_never_use_footways():
    footway_pts = set()
    for w in OSM_WAYS.values():
        if w["tags"].get("highway") in calib.WALK_HW - calib.DRIVE_HW:
            footway_pts.update(OSM_NODES[n] for n in w["nodes"])
    drive_pts = set()
    for w in OSM_WAYS.values():
        if w["tags"].get("highway") in calib.DRIVE_HW:
            drive_pts.update(OSM_NODES[n] for n in w["nodes"])
    for r in CFG["roads"]:
        if r["is_driveable"]:
            for pt in r["geometry"][1:-1]:
                p = (round(pt["lat"], 7), round(pt["lng"], 7))
                assert not (p in footway_pts and p not in drive_pts), f"{r['road_id']} uses a footway"


# ------------------------------------------------------ routing weights unchanged
def test_existing_routing_weights_are_unchanged_from_baseline():
    """Every pre-existing road/edge keeps its exact weights, so committed (seeded) experiment results
    stay reproducible. Only the new LH-3 roads, which have no earlier value, are added."""
    roads = {r["road_id"]: r for r in CFG["roads"]}
    assert set(roads) == (set(BASELINE["roads"]) - REMOVED_ROADS) | NEW_ROAD_IDS, "road set changed unexpectedly"
    for rid, b in BASELINE["roads"].items():
        if rid in REMOVED_ROADS:
            continue
        r = roads[rid]
        assert r["length_meters"] == b["length_meters"], rid
        assert r["expected_travel_time_seconds"] == b["expected_travel_time_seconds"], rid
        assert (r["start_node_id"], r["end_node_id"]) == (b["start"], b["end"]), rid
        assert (r["is_walkable"], r["is_driveable"], r["status"]) == (b["is_walkable"], b["is_driveable"], b["status"]), rid
        assert r.get("weights_source") is None, f"{rid}: existing weights must not be derived"
    new_edges = {(e["from_node_id"], e["to_node_id"]): e for e in CFG["edges"]}
    kept_edges = [b for b in BASELINE["edges"] if b["road_id"] not in REMOVED_ROADS]
    for b in kept_edges:
        assert {k: new_edges[(b["from_node_id"], b["to_node_id"])][k] for k in b} == b, b
    extra = {k: e for k, e in new_edges.items() if e["road_id"] in NEW_ROAD_IDS}
    assert len(new_edges) == len(kept_edges) + len(extra) == len(CFG["edges"])
    assert len(extra) == 4, "each new road needs both directions"


def test_new_road_weights_are_derived_from_osm_geometry_and_disclosed():
    for r in CFG["roads"]:
        if r["road_id"] not in NEW_ROAD_IDS:
            continue
        assert r["weights_source"] == "osm_geometry", r["road_id"]
        pts = [(p["lat"], p["lng"]) for p in r["geometry"]]
        length = round(sum(_haversine_m(a, b) for a, b in zip(pts, pts[1:])))
        assert abs(r["length_meters"] - length) <= 2, r["road_id"]
        assert r["expected_travel_time_seconds"] == round(r["length_meters"] * 0.8), r["road_id"]
        for e in CFG["edges"]:
            if e["road_id"] == r["road_id"]:
                assert (e["weight_distance_meters"], e["weight_time_seconds"]) == (
                    r["length_meters"], r["expected_travel_time_seconds"]), r["road_id"]


def test_seeded_simulation_destination_set_is_unchanged():
    """The engine draws vehicle destinations from the destinations table; any change to that set
    shifts every seeded result. New destinations must stay out of the draw."""
    demand = sorted(d["destination_id"] for d in CFG["destinations"] if d.get("include_in_simulation", True))
    assert demand == BASELINE_DEMAND
    assert NEW_DEST_IDS.isdisjoint(demand)


def test_engine_draws_only_baseline_destinations(tmp_path):
    from digital_twin.simulation.engine import SimulationEngine
    conn = sqlite3.connect(tmp_path / "eng.db")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    load_campus_config(ROOT / "configs" / "campus" / "vitap.yaml", conn)
    assert sorted(SimulationEngine._load_destination_ids("vitap", conn)) == BASELINE_DEMAND
    assert conn.execute("SELECT COUNT(*) FROM destinations WHERE campus_id='vitap'").fetchone()[0] == len(CFG["destinations"])
    conn.close()


def test_requested_buildings_are_placed_exactly_and_reachable():
    """MH-5 and LH-3 (plus MH-4, LH-2) are real OSM buildings with drawn roads from their lots."""
    items = _items()
    for name in ("MH-5", "LH-3", "MH-4", "LH-2"):
        it = next(v for v in items.values() if v["name"] == name)
        assert it["coordinate_source"].startswith("osm_relation:") and "latitude" in it, name
        nid = it["destination_id"]
        drawn = [r for r in CFG["roads"] if r["end_node_id"] == nid and r["geometry_source"] == "osm_snapped"]
        assert drawn, f"{name} has no drawn road"


# ------------------------------------------------------------- API / DB / routing
def test_api_campus_serves_yaml_coordinates_and_provenance(client):
    body = client.get("/campus").json()
    items = _items()
    for section in ("gates", "parking_lots", "destinations"):
        assert body[section], section
        for it in body[section]:
            cfg = items[it["id"]]
            if it["id"] in UNCONFIGURED:
                assert it["lat"] is None and it["lng"] is None and it["coordinate_source"] == "unplaced"
                assert it["exact"] is False
                continue
            assert (it["lat"], it["lng"]) == (cfg["latitude"], cfg["longitude"]), it["id"]
            assert it["coordinate_source"] == cfg["coordinate_source"], it["id"]
            assert it["accuracy_m"] == cfg["coordinate_accuracy_m"], it["id"]
            assert it["exact"] == _is_exact(cfg["coordinate_source"]), it["id"]
    roads = {r["road_id"]: r for r in CFG["roads"]}
    assert {r["id"] for r in body["roads"]} == set(roads)
    for road in body["roads"]:
        assert road["geometry"] == roads[road["id"]]["geometry"], road["id"]
        assert road["geometry_source"] == roads[road["id"]]["geometry_source"], road["id"]
    assert not any(r["geometry_source"] == "unplaced" for r in body["roads"])
    assert {d["id"] for d in body["destinations"]} == set(BASELINE_DEMAND) | NEW_DEST_IDS
    assert not ({d["id"] for d in body["destinations"]} & REMOVED)


def test_api_exposes_only_real_boundaries(client):
    lots = {l["id"]: l for l in client.get("/campus").json()["parking_lots"]}
    overflow = lots["vitap-lot-overflow"]
    assert len(overflow["boundary"]) == 2, "overflow should expose both real OSM footprints"
    assert all(len(ring) >= 4 for ring in overflow["boundary"])
    for lid, lot in lots.items():
        if lid != "vitap-lot-overflow":
            assert lot["boundary_source"] == "placeholder" and lot["boundary"] == [], lid


def _lat_lng(points):
    return [(p["lat"], p["lng"]) for p in points]


def test_route_geometry_follows_road_polyline(client):
    road = next(r for r in CFG["roads"] if r["road_id"] == "vitap-road-main-gate-to-sports-lot")
    expected = [(p["lat"], p["lng"]) for p in road["geometry"]]
    fwd = client.get("/route", params={"origin": "vitap-gate-main", "destination": "vitap-lot-sports", "mode": "drive"})
    assert fwd.status_code == 200
    got = fwd.json()["geometry"]
    assert len(got) > 2
    assert _lat_lng(got) == expected


def test_route_geometry_is_oriented_in_direction_of_travel(client):
    road = next(r for r in CFG["roads"] if r["road_id"] == "vitap-road-main-gate-to-sports-lot")
    expected = list(reversed([(p["lat"], p["lng"]) for p in road["geometry"]]))
    rev = client.get("/route", params={"origin": "vitap-lot-sports", "destination": "vitap-gate-main", "mode": "drive"})
    assert rev.status_code == 200
    assert _lat_lng(rev.json()["geometry"]) == expected


def test_multi_hop_route_is_continuous_with_no_repeated_joint(client):
    nodes = _nodes()
    resp = client.get("/route", params={"origin": "vitap-gate-main", "destination": "vitap-osm-1485919486", "mode": "walk"})
    assert resp.status_code == 200
    geo = _lat_lng(resp.json()["geometry"])
    assert geo[0] == nodes["vitap-gate-main"]
    assert geo[-1] == nodes["vitap-osm-1485919486"]
    assert all(a != b for a, b in zip(geo, geo[1:])), "duplicate joint point between segments"


def test_every_destination_is_routable_from_both_gates(client):
    """Dijkstra still reaches every configured destination on the recalibrated graph."""
    for d in CFG["destinations"]:
        for gate in ("vitap-gate-main", "vitap-gate-visitor"):
            r = client.get("/route", params={"origin": gate, "destination": d["destination_id"], "mode": "walk"})
            assert r.status_code == 200, f"{gate} -> {d['name']}: {r.text}"


def test_find_parking_still_ranks_lots_with_aligned_routes(client):
    r = client.get("/find_parking", params={"destination_id": "vitap-osm-1485919486"})
    assert r.status_code == 200
    body = r.json()
    assert body["options"], "no parking options returned"
    opt = body["options"][0]
    assert len(opt["drive_route"]["geometry"]) > 2 and len(opt["walk_route"]["geometry"]) > 2


def test_loader_prunes_rows_no_longer_in_config(tmp_path):
    """A DB built from an older config must not keep serving removed destinations/roads."""
    conn = sqlite3.connect(tmp_path / "stale.db")
    conn.row_factory = sqlite3.Row
    apply_migrations(conn)
    cfg_path = ROOT / "configs" / "campus" / "vitap.yaml"
    load_campus_config(cfg_path, conn)
    conn.execute(
        "INSERT INTO destinations (campus_id, destination_id, name, category, latitude, longitude, configuration_version) "
        "VALUES ('vitap','vitap-osm-fake-001','FAKE','academic_block',16.4945,80.4960,'old')")
    conn.execute(
        "INSERT INTO roads (campus_id, road_id, name, start_node_id, end_node_id, length_meters, geometry, configuration_version) "
        "VALUES ('vitap','vitap-road-fake','x','vitap-lot-academic-main','vitap-osm-fake-001',380,'[]','old')")
    conn.execute(
        "INSERT INTO destinations (campus_id, destination_id, name, category, latitude, longitude, configuration_version) "
        "VALUES ('vitap','vitap-osm-ap2-001','AP-2','academic_block',16.4945,80.4960,'old')")
    conn.execute(
        "INSERT INTO roads (campus_id, road_id, name, start_node_id, end_node_id, length_meters, geometry, configuration_version) "
        "VALUES ('vitap','vitap-road-academic-lot-to-ap2','x','vitap-lot-academic-main','vitap-osm-ap2-001',380,'[]','old')")
    conn.commit()
    load_campus_config(cfg_path, conn)
    assert conn.execute("SELECT COUNT(*) FROM destinations WHERE destination_id='vitap-osm-ap2-001'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM roads WHERE road_id='vitap-road-academic-lot-to-ap2'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM destinations WHERE destination_id='vitap-osm-fake-001'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM roads WHERE road_id='vitap-road-fake'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM destinations WHERE campus_id='vitap'").fetchone()[0] == len(CFG["destinations"])
    conn.close()
