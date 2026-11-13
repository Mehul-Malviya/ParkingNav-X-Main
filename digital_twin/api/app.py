"""
ParkingNav-X REST API
VIT-AP University Smart Parking Digital Twin
"""
import hmac
import json
import math
import os
import re
import statistics
import uuid
from pathlib import Path
from typing import List, Optional

import networkx as nx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.graph_service import CampusGraphService
from digital_twin.simulation.demo_strategies import ParkingNavXFullStrategy, PredictionOnlyStrategy
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy, NearestAvailableStrategy

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "digital_twin.db"
CAMPUS_YAML = ROOT / "configs" / "campus" / "vitap.yaml"
SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"
RESULTS_FILE = ROOT / "experiments" / "results" / "all_results.json"
SUMMARY_FILE = ROOT / "experiments" / "results" / "results_summary.json"

app = FastAPI(
    title="ParkingNav-X API",
    description="VIT-AP University Smart Parking Digital Twin — REST API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # PARKINGNAV_ALLOWED_ORIGINS: comma-separated origins for a live deployment; unset = any origin (dev).
    allow_origins=[o.strip() for o in os.environ.get("PARKINGNAV_ALLOWED_ORIGINS", "*").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

def require_write_key(x_api_key: Optional[str] = Header(default=None)):
    """Guard for endpoints that change data. If PARKINGNAV_API_KEY is set (live deployment), requests must send
    it as an X-API-Key header; if unset (local dev, tests) the endpoints stay open."""
    key = os.environ.get("PARKINGNAV_API_KEY")
    if key and not hmac.compare_digest(x_api_key or "", key):
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


STRATEGIES = {
    "B1": FirstAvailableStrategy(),
    "B2": NearestAvailableStrategy(),
    "B3": PredictionOnlyStrategy(),
    "P":  ParkingNavXFullStrategy(),
}

_graph_service = CampusGraphService()

# ── Cached DB connection (migrations run once at startup, not per-request) ────
_db_conn = None


def get_conn():
    global _db_conn
    if _db_conn is None:
        _db_conn = get_connection(DB_PATH)
        apply_migrations(_db_conn)
        load_campus_config(CAMPUS_YAML, _db_conn)
    return _db_conn


@app.on_event("startup")
def _startup_prewarm():
    """Pre-warm the prediction engine so the first API request is not slow."""
    try:
        from digital_twin.prediction.engine import retrain
        retrain(get_conn())  # fits all models once (real data where available); cached as singleton
    except Exception:
        pass  # non-fatal — predictions will fall back to MovingAverage


def _build_graph(conn):
    return _graph_service.build_graph("vitap", conn)


def _provenance(source, accuracy_m):
    """How a coordinate was obtained. exact == taken from an OpenStreetMap way."""
    return {
        "coordinate_source": source,
        "accuracy_m": accuracy_m,
        "exact": bool(source and source.startswith(("osm_way", "osm_relation"))),
    }


def _parse_boundary(raw):
    """Stored boundary_polygon (JSON string of lat-first POLYGON/MULTIPOLYGON text)
    -> list of rings, each a list of {"lat", "lng"}."""
    if not raw:
        return []
    text = json.loads(raw) if raw.startswith('"') else raw
    rings = []
    for ring in re.findall(r"\(([^()]+)\)", text):
        pts = []
        for pair in ring.split(","):
            lat, lng = pair.split()
            pts.append({"lat": float(lat), "lng": float(lng)})
        rings.append(pts)
    return rings


def _route_geometry(graph, path):
    """Polyline for a routed path, as [{"lat", "lng"}, ...].

    Follows each traversed road's own geometry (the same polyline /campus draws),
    so a highlighted route lies on the roads instead of cutting straight between
    node centres. Falls back to node coordinates where a road has no geometry.
    """
    points = []

    def _add(lat, lng):
        if lat is None or lng is None:
            return
        pt = {"lat": lat, "lng": lng}
        if not points or points[-1] != pt:
            points.append(pt)

    for i, node_id in enumerate(path):
        if i > 0:
            edge = graph.edges[path[i - 1], node_id]
            for p in edge.get("geometry") or []:
                _add(p["lat"], p["lng"])
        nd = graph.nodes[node_id]
        _add(nd.get("latitude"), nd.get("longitude"))
    return points


# ── Models ────────────────────────────────────────────────────────────────────

class SimulateRequest(BaseModel):
    scenario: str = "E1_normal_day"
    strategy: str = "P"


class PredictRequest(BaseModel):
    lot_id: str
    horizon_minutes: int = 15


class OptimizeRequest(BaseModel):
    scenario: str = "E1_normal_day"
    weight_profile: str = "P1"


class RouteRequest(BaseModel):
    origin: str
    destination: str
    mode: str = "drive"  # drive | walk


class OperatorOverrideRequest(BaseModel):
    lot_id: str
    action: str          # "close" | "open" | "cap_override"
    reason: str = ""
    override_capacity: Optional[int] = None  # used with action="cap_override"


class ObservationRecord(BaseModel):
    timestamp: str           # ISO-8601
    lot_id: str
    occupied_spaces: int
    gate_id: Optional[str] = None
    vehicle_count: Optional[int] = None
    source: str = "sensor"   # sensor | manual | synthetic


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Info"])
def health():
    """Liveness check — returns 200 when the API is up and the DB is reachable."""
    try:
        conn = get_conn()
        conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok, "version": "2.0.0"}


@app.get("/", tags=["Info"])
def root():
    return {
        "project": "ParkingNav-X",
        "campus": "VIT-AP University, Amaravati, Andhra Pradesh",
        "version": "2.0.0",
        "docs": "/docs",
    }


@app.get("/campus", tags=["Campus"])
def get_campus():
    """Return VIT-AP campus summary: gates, parking lots, roads, destinations."""
    conn = get_conn()
    gates = conn.execute(
        "SELECT gate_id, name, latitude, longitude, capacity, status, coordinate_source, coordinate_accuracy_m "
        "FROM gates WHERE campus_id='vitap'"
    ).fetchall()
    lots = conn.execute(
        "SELECT parking_lot_id, name, latitude, longitude, total_capacity, usable_capacity, status, "
        "coordinate_source, coordinate_accuracy_m, boundary_polygon, boundary_source "
        "FROM parking_lots WHERE campus_id='vitap'"
    ).fetchall()
    roads = conn.execute(
        "SELECT road_id, name, start_node_id, end_node_id, length_meters, expected_travel_time_seconds, is_walkable, is_driveable, status, geometry, geometry_source, access_start_m, access_end_m FROM roads WHERE campus_id='vitap'"
    ).fetchall()
    dests = conn.execute(
        "SELECT destination_id, name, category, latitude, longitude, nearest_parking_lot_ids, "
        "coordinate_source, coordinate_accuracy_m FROM destinations WHERE campus_id='vitap'"
    ).fetchall()

    return {
        "campus_id": "vitap",
        "name": "VIT-AP University",
        "location": "Amaravati, Andhra Pradesh, India",
        "gates": [
            {"id": r[0], "name": r[1], "lat": r[2], "lng": r[3], "capacity": r[4], "status": r[5],
             **_provenance(r[6], r[7])}
            for r in gates
        ],
        "parking_lots": [
            {"id": r[0], "name": r[1], "lat": r[2], "lng": r[3],
             "total_capacity": r[4], "usable_capacity": r[5], "status": r[6],
             **_provenance(r[7], r[8]),
             "boundary_source": r[10],
             # Only a real footprint is exposed as a boundary; a "placeholder" box is not drawn as one.
             "boundary": _parse_boundary(r[9]) if r[10] and r[10].startswith("osm_way") else []}
            for r in lots
        ],
        "roads": [
            {
                "id": r[0], "name": r[1],
                "start_node_id": r[2], "end_node_id": r[3],
                "length_meters": r[4], "travel_time_seconds": r[5],
                "is_walkable": bool(r[6]), "is_driveable": bool(r[7]),
                "status": r[8],
                "geometry": json.loads(r[9]) if r[9] else [],
                "geometry_source": r[10],
                # metres at each end that are not on a mapped road (drawn dotted by the UI)
                "access_start_m": r[11],
                "access_end_m": r[12],
            }
            for r in roads
        ],
        "destinations": [
            {
                "id": r[0], "name": r[1], "category": r[2],
                "lat": r[3], "lng": r[4],
                "nearest_lots": json.loads(r[5]) if r[5] else [],
                **_provenance(r[6], r[7]),
            }
            for r in dests
        ],
    }


@app.post("/operator/override", tags=["Operator"])
def operator_override(req: OperatorOverrideRequest):
    """
    Operator override: close/reopen a lot or change its usable capacity.
    Changes take effect immediately in the live Digital Twin state.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT usable_capacity, status FROM parking_lots WHERE campus_id='vitap' AND parking_lot_id=?",
        (req.lot_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Lot '{req.lot_id}' not found")

    allowed_actions = {"close", "open", "cap_override"}
    if req.action not in allowed_actions:
        raise HTTPException(status_code=400, detail=f"action must be one of {allowed_actions}")

    if req.action == "close":
        conn.execute(
            "UPDATE parking_lots SET status='closed' WHERE campus_id='vitap' AND parking_lot_id=?",
            (req.lot_id,)
        )
        new_status, new_cap = "closed", row[0]
    elif req.action == "open":
        conn.execute(
            "UPDATE parking_lots SET status='open' WHERE campus_id='vitap' AND parking_lot_id=?",
            (req.lot_id,)
        )
        new_status, new_cap = "open", row[0]
    else:  # cap_override
        if req.override_capacity is None or req.override_capacity <= 0:
            raise HTTPException(status_code=400, detail="override_capacity must be a positive integer")
        conn.execute(
            "UPDATE parking_lots SET usable_capacity=? WHERE campus_id='vitap' AND parking_lot_id=?",
            (req.override_capacity, req.lot_id)
        )
        new_status, new_cap = row[1], req.override_capacity

    conn.commit()
    return {
        "lot_id": req.lot_id,
        "action": req.action,
        "new_status": new_status,
        "new_usable_capacity": new_cap,
        "reason": req.reason,
        "note": "Override applied to live DB. Run /simulate to propagate into next simulation.",
    }


@app.post("/observations", tags=["Campus"], dependencies=[Depends(require_write_key)])
def post_observation(obs: ObservationRecord):
    """
    Record one occupancy reading. source=sensor|manual counts as real data (live forecasts, retraining);
    source=synthetic is stored but never treated as real. A naive timestamp is campus-local (IST).
    """
    from digital_twin.observations import record_observations
    res = record_observations(get_conn(), [obs.model_dump()])
    if res["rejected"]:
        err = res["rejected"][0]["error"]
        raise HTTPException(status_code=404 if err.startswith("unknown lot") else 400, detail=err)
    return {**res, "lot_id": obs.lot_id, "occupied_spaces": obs.occupied_spaces,
            "timestamp": obs.timestamp, "source": obs.source}


@app.post("/observations/batch", tags=["Campus"], dependencies=[Depends(require_write_key)])
def post_observations_batch(batch: List[ObservationRecord]):
    """Record many readings at once. Bad rows are reported, good rows are still stored; duplicates are skipped."""
    from digital_twin.observations import record_observations
    return record_observations(get_conn(), [o.model_dump() for o in batch])


@app.get("/campus/graph", tags=["Campus"])
def get_campus_graph():
    """Return full campus graph (nodes + edges) for routing visualization."""
    conn = get_conn()
    graph = _build_graph(conn)
    return _graph_service.to_json(graph)


@app.get("/scenarios", tags=["Simulation"])
def list_scenarios():
    files = sorted(SCENARIO_DIR.glob("*.yaml"))
    return {"scenarios": [f.stem for f in files]}


@app.get("/strategies", tags=["Simulation"])
def list_strategies():
    return {
        "strategies": [
            {"code": "B1", "name": "First Available",     "description": "Naive — assigns first open lot found"},
            {"code": "B2", "name": "Nearest Available",   "description": "Picks the closest open lot by distance"},
            {"code": "B3", "name": "Prediction Only",     "description": "Avoids nearly-full lots using fill-rate forecast"},
            {"code": "P",  "name": "ParkingNav-X (full)", "description": "Prediction + gate load balancing + zone routing"},
        ]
    }


@app.post("/simulate", tags=["Simulation"])
def simulate(req: SimulateRequest):
    scenario_file = SCENARIO_DIR / f"{req.scenario}.yaml"
    if not scenario_file.exists():
        available = [f.stem for f in SCENARIO_DIR.glob("*.yaml")]
        raise HTTPException(status_code=404, detail=f"Scenario '{req.scenario}' not found. Available: {available}")

    strategy = STRATEGIES.get(req.strategy)
    if not strategy:
        raise HTTPException(status_code=400, detail=f"Strategy must be one of: {list(STRATEGIES.keys())}")

    conn = get_conn()
    scenario = ScenarioLoader.load(scenario_file)
    engine = SimulationEngine()
    run_id = f"api-{uuid.uuid4().hex[:8]}"
    result = engine.run(scenario, strategy, conn, run_id=run_id)

    # Populate lot_occupancy_history so the risk engine sees real data
    if result.timesteps:
        last_ts = result.timesteps[-1]
        lot_ids = [k.replace("parking_occupancy_", "") for k in last_ts if k.startswith("parking_occupancy_")]
        for lot_id in lot_ids:
            occupied = last_ts.get(f"parking_occupancy_{lot_id}", 0)
            cap = last_ts.get(f"parking_capacity_{lot_id}", 1) or 1
            fill_rate = round(occupied / cap, 4)
            try:
                conn.execute(
                    "INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, source) "
                    "VALUES (?, ?, ?, 'simulation')",
                    (lot_id, int(occupied), fill_rate),
                )
            except Exception:
                pass
        conn.commit()

    m = result.metrics
    return {
        "run_id": run_id,
        "scenario": req.scenario,
        "strategy": req.strategy,
        "campus": "vitap",
        "duration_min": scenario.duration_minutes,
        "vehicles": scenario.vehicle_count,
        "metrics": {
            "total_vehicles":       m.get("total_vehicles"),
            "parked_vehicles":      m.get("parked_vehicles"),
            "completed_trips":      m.get("completed_vehicles"),
            "overflow_events":      m.get("overflow_events_count"),
            "avg_search_time_min":  round(m["avg_search_time_min"], 2) if m.get("avg_search_time_min") is not None else None,
            "avg_wait_time_min":    round(m["avg_wait_time_min"], 2)   if m.get("avg_wait_time_min")   is not None else None,
            "avg_gate_queue":       round(m["avg_gate_queue"], 2)      if m.get("avg_gate_queue")      is not None else None,
            "peak_gate_queue":      m.get("max_gate_queue"),
        },
    }


@app.get("/compare/{scenario}", tags=["Simulation"])
def compare_strategies(scenario: str):
    """Run all 4 strategies on a scenario and return side-by-side comparison."""
    scenario_file = SCENARIO_DIR / f"{scenario}.yaml"
    if not scenario_file.exists():
        available = [f.stem for f in SCENARIO_DIR.glob("*.yaml")]
        raise HTTPException(status_code=404, detail=f"Scenario '{scenario}' not found. Available: {available}")

    conn = get_conn()
    results = {}
    for code in ["B1", "B2", "B3", "P"]:
        strategy = STRATEGIES[code]
        sc = ScenarioLoader.load(scenario_file)
        engine = SimulationEngine()
        run_id = f"api-cmp-{uuid.uuid4().hex[:6]}"
        try:
            result = engine.run(sc, strategy, conn, run_id=run_id)
        except Exception as e:  # surface the real cause to the UI instead of a bare 500
            raise HTTPException(
                status_code=500,
                detail=f"Strategy {code} failed on '{scenario}': {type(e).__name__}: {e}",
            )
        m = result.metrics
        results[code] = {
            "overflow_events":     m.get("overflow_events_count"),
            "avg_search_time_min": round(m["avg_search_time_min"], 2) if m.get("avg_search_time_min") is not None else None,
            "avg_wait_time_min":   round(m["avg_wait_time_min"], 2)   if m.get("avg_wait_time_min")   is not None else None,
            "avg_gate_queue":      round(m["avg_gate_queue"], 2)      if m.get("avg_gate_queue")      is not None else None,
            "peak_gate_queue":     m.get("max_gate_queue"),
        }
    return {"scenario": scenario, "comparison": results}


@app.get("/events", tags=["Campus"])
def get_events():
    conn = get_conn()
    rows = conn.execute(
        "SELECT event_id, event_type, name, start_time, end_time, status FROM events WHERE campus_id='vitap'"
    ).fetchall()
    return {
        "campus": "vitap",
        "events": [
            {"id": r[0], "type": r[1], "name": r[2], "start": r[3], "end": r[4], "status": r[5]}
            for r in rows
        ],
    }


# ── Routing endpoints ──────────────────────────────────────────────────────────

@app.get("/route", tags=["Routing"])
def get_route(origin: str, destination: str, mode: str = "drive"):
    """
    Compute shortest path between two campus nodes.

    - **origin**: node_id (gate, parking_lot, or destination)
    - **destination**: node_id
    - **mode**: 'drive' (driveable roads only) or 'walk' (walkable paths)
    """
    conn = get_conn()
    graph = _build_graph(conn)

    if origin not in graph:
        raise HTTPException(status_code=404, detail=f"Origin '{origin}' not found in campus graph")
    if destination not in graph:
        raise HTTPException(status_code=404, detail=f"Destination '{destination}' not found in campus graph")

    # Filter subgraph by mode and open status
    def edge_filter(u, v, data):
        if data.get("status") != "open":
            return False
        if mode == "drive":
            return bool(data.get("is_driveable"))
        return bool(data.get("is_walkable"))

    filtered = nx.subgraph_view(
        graph,
        filter_edge=lambda u, v, k=None: edge_filter(u, v, graph.edges[u, v])
        if not k else edge_filter(u, v, graph.edges[u, v, k])
    )

    try:
        path = nx.dijkstra_path(
            filtered, origin, destination,
            weight="weight_time_seconds"
        )
        length = nx.dijkstra_path_length(
            filtered, origin, destination,
            weight="weight_time_seconds"
        )
        dist = nx.dijkstra_path_length(
            filtered, origin, destination,
            weight="weight_distance_meters"
        )
    except nx.NetworkXNoPath:
        raise HTTPException(
            status_code=422,
            detail=f"No {mode} route from '{origin}' to '{destination}'. Check road closures or mode restrictions."
        )
    except nx.NodeNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))

    geometry = _route_geometry(graph, path)

    # Build segment list
    segments = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        if graph.has_edge(u, v):
            edge = graph.edges[u, v]
            segments.append({
                "from": u,
                "to": v,
                "road_id": edge.get("road_id"),
                "time_seconds": edge.get("weight_time_seconds"),
                "distance_meters": edge.get("weight_distance_meters"),
                "is_driveable": edge.get("is_driveable"),
                "is_walkable": edge.get("is_walkable"),
            })

    return {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "path": path,
        "total_time_seconds": round(length),
        "total_distance_meters": round(dist),
        "total_time_minutes": round(length / 60, 1),
        "segments": segments,
        "geometry": geometry,
    }


@app.get("/find_parking", tags=["Routing"])
def find_parking(destination_id: str, gate_id: str = "vitap-gate-main"):
    """
    Find the best parking lot for a given destination, with vehicle + walking routes.

    Returns ranked parking options:
    - Vehicle route: gate → parking lot (driveable)
    - Walking route: parking lot → destination (walkable)
    - Scores by predicted fill rate + total travel time
    """
    conn = get_conn()
    graph = _build_graph(conn)

    # Get all open parking lots
    lots = conn.execute(
        "SELECT parking_lot_id, name, usable_capacity, status FROM parking_lots WHERE campus_id='vitap' AND status='open'"
    ).fetchall()

    # Get destination info
    dest_row = conn.execute(
        "SELECT destination_id, name, category, nearest_parking_lot_ids FROM destinations WHERE campus_id='vitap' AND destination_id=?",
        (destination_id,)
    ).fetchone()

    if not dest_row:
        raise HTTPException(status_code=404, detail=f"Destination '{destination_id}' not found")

    # Get predictions for fill rates
    try:
        from digital_twin.prediction.engine import forecast_context
        predictor, _basis = forecast_context(conn)
        preds = predictor.predict_all(15)
    except Exception:
        preds = {}

    # Preferred lots from destination config
    preferred_lots = []
    if dest_row[3]:
        try:
            preferred_lots = json.loads(dest_row[3])
        except Exception:
            preferred_lots = []

    def _try_route(origin, dest, mode):
        def edge_filter(u, v, data):
            if data.get("status") != "open":
                return False
            if mode == "drive":
                return bool(data.get("is_driveable"))
            return bool(data.get("is_walkable"))

        filtered = nx.subgraph_view(
            graph,
            filter_edge=lambda u, v, k=None: edge_filter(u, v, graph.edges[u, v])
        )
        try:
            path = nx.dijkstra_path(filtered, origin, dest, weight="weight_time_seconds")
            t = nx.dijkstra_path_length(filtered, origin, dest, weight="weight_time_seconds")
            d = nx.dijkstra_path_length(filtered, origin, dest, weight="weight_distance_meters")
            geo = _route_geometry(graph, path)
            return {"path": path, "time_seconds": round(t), "distance_meters": round(d), "geometry": geo}
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return None

    options = []
    for lot in lots:
        lot_id = lot[0]
        lot_name = lot[1]
        capacity = lot[2]

        # Get fill rate prediction
        pred = preds.get(lot_id, {})
        fill_rate = pred.get("fill_rate", 0.4) if pred else 0.4
        available = int(capacity * (1 - fill_rate))

        # Compute drive route: gate → lot
        drive_route = _try_route(gate_id, lot_id, "drive")
        if not drive_route:
            continue  # skip unreachable lots

        # Compute walk route: lot → destination
        walk_route = _try_route(lot_id, destination_id, "walk")
        if not walk_route:
            continue  # skip if no walking path to destination

        # Scoring: lower is better
        # 40% drive time + 40% walk time + 20% fill penalty
        drive_t = drive_route["time_seconds"]
        walk_t = walk_route["time_seconds"]
        fill_penalty = fill_rate * 300  # up to 5 min penalty at full
        score = 0.4 * drive_t + 0.4 * walk_t + 0.2 * fill_penalty

        is_preferred = lot_id in preferred_lots
        if is_preferred:
            score *= 0.85  # 15% bonus for recommended lots

        # Cost breakdown for this lot (M4/M9 spec: expose individual cost components)
        fill_penalty_norm = min(1.0, fill_rate * 1.2)
        drive_norm = min(1.0, drive_t / 600.0)   # 600s = 10 min reference
        walk_norm = min(1.0, walk_t / 600.0)
        cost_breakdown = {
            "search_travel_cost": round(0.4 * drive_norm + 0.4 * walk_norm, 4),
            "fill_penalty_cost": round(0.2 * fill_penalty_norm, 4),
            "total_score": round(score, 1),
            "components": {
                "drive_time_seconds": round(drive_t),
                "walk_time_seconds": round(walk_t),
                "fill_rate": round(fill_rate, 3),
                "fill_penalty_seconds": round(fill_rate * 300),
            },
        }
        pred_detail = preds.get(lot_id, {})
        options.append({
            "lot_id": lot_id,
            "lot_name": lot_name,
            "capacity": capacity,
            "estimated_available": max(0, available),
            "predicted_fill_rate": round(fill_rate, 3),
            "predicted_fill_pct": round(fill_rate * 100, 1),
            "prediction_interval_90": {
                "lower_pct": round(float(pred_detail.get("lower_90", fill_rate * 0.9)) * 100, 1),
                "upper_pct": round(float(pred_detail.get("upper_90", min(1.0, fill_rate * 1.1))) * 100, 1),
            } if pred_detail else None,
            "is_preferred_for_destination": is_preferred,
            "drive_route": drive_route,
            "walk_route": walk_route,
            "total_time_seconds": round(drive_t + walk_t),
            "total_time_minutes": round((drive_t + walk_t) / 60, 1),
            "drive_time_minutes": round(drive_t / 60, 1),
            "walk_time_minutes": round(walk_t / 60, 1),
            "score": round(score, 1),
            "cost_breakdown": cost_breakdown,
            "recommendation_reason": _explain(lot_name, fill_rate, drive_t, walk_t, is_preferred),
        })

    options.sort(key=lambda x: x["score"])

    # Assign ranks and build structured explanation for top choice (M9)
    for i, opt in enumerate(options):
        opt["rank"] = i + 1
    best = options[0] if options else None
    explanation = None
    if best:
        pred_d = preds.get(best["lot_id"], {})
        explanation = _explain_structured(
            lot_id=best["lot_id"],
            lot_name=best["lot_name"],
            fill_rate=best["predicted_fill_rate"],
            drive_t=best["drive_route"]["time_seconds"],
            walk_t=best["walk_route"]["time_seconds"],
            preferred=best["is_preferred_for_destination"],
            lower_90=float(pred_d.get("lower_90", best["predicted_fill_rate"] * 0.9)) if pred_d else None,
            upper_90=float(pred_d.get("upper_90", min(1.0, best["predicted_fill_rate"] * 1.1))) if pred_d else None,
            objective_score=best["score"],
            rank=1,
            alternatives=options[1:3],
        )

    return {
        "destination_id": destination_id,
        "destination_name": dest_row[1],
        "destination_category": dest_row[2],
        "gate_used": gate_id,
        "options_count": len(options),
        "best": best,
        "explanation": explanation,
        "options": options[:5],  # top 5
        "note": "[SYNTHETIC] Fill rates from XGBoost model trained on synthetic data. Not real occupancy.",
    }


def _explain(lot_name, fill_rate, drive_t, walk_t, preferred):
    parts = []
    if preferred:
        parts.append("Nearest to your destination")
    if fill_rate < 0.5:
        parts.append(f"{(1-fill_rate)*100:.0f}% capacity available")
    elif fill_rate < 0.8:
        parts.append(f"Moderately occupied ({fill_rate*100:.0f}%)")
    else:
        parts.append(f"Near capacity ({fill_rate*100:.0f}%) — consider alternatives")
    parts.append(f"{round(drive_t/60, 1)} min drive + {round(walk_t/60, 1)} min walk")
    return ". ".join(parts)


def _explain_structured(lot_id, lot_name, fill_rate, drive_t, walk_t, preferred,
                         lower_90=None, upper_90=None, objective_score=None, rank=None,
                         risk_level=None, alternatives=None):
    """Return a structured explanation object matching M9 spec requirements."""
    if fill_rate < 0.5:
        occupancy_status = "low"
    elif fill_rate < 0.80:
        occupancy_status = "moderate"
    elif fill_rate < 0.90:
        occupancy_status = "high"
    else:
        occupancy_status = "critical"

    explanation = {
        "lot_id": lot_id,
        "lot_name": lot_name,
        "chosen": preferred or (rank == 1),
        "current_fill_pct": round(fill_rate * 100, 1),
        "occupancy_status": occupancy_status,
        "predicted_fill_pct": round(fill_rate * 100, 1),
        "prediction_interval_90": (
            {"lower_pct": round((lower_90 or fill_rate) * 100, 1),
             "upper_pct": round((upper_90 or fill_rate) * 100, 1)}
            if lower_90 is not None else None
        ),
        "drive_time_min": round(drive_t / 60, 1),
        "walk_time_min": round(walk_t / 60, 1),
        "total_time_min": round((drive_t + walk_t) / 60, 1),
        "risk_level": risk_level or ("HIGH" if fill_rate >= 0.90 else "MEDIUM" if fill_rate >= 0.75 else "LOW"),
        "objective_score": round(objective_score, 4) if objective_score is not None else None,
        "rank": rank,
        "preferred_for_destination": preferred,
        "why_chosen": _explain(lot_name, fill_rate, drive_t, walk_t, preferred),
        "alternatives_count": len(alternatives) if alternatives else 0,
        "fallback_used": False,
    }
    return explanation


# ── Prediction endpoints ───────────────────────────────────────────────────────

def _data_source_label(prefix: str) -> str:
    from digital_twin.prediction.engine import data_description
    d = data_description()
    return f"[SYNTHETIC] {prefix} synthetic demand data" if d["mode"] == "synthetic" else f"[{d['mode'].upper()}] {prefix} {d['label']}"


@app.post("/predict/retrain", tags=["Prediction"], dependencies=[Depends(require_write_key)])
def retrain_predictor():
    """Refit the forecast models on current data: real recorded occupancy for every lot with at least a week
    of readings, synthetic for the rest. Run after importing or posting real observations."""
    from digital_twin.prediction.engine import retrain
    return retrain(get_conn())


@app.get("/predict/occupancy", tags=["Prediction"])
def predict_occupancy(lot_id: str = "vitap-lot-academic-main", horizon_minutes: int = 15,
                      as_of: Optional[str] = None):
    """Predict occupancy for a parking lot at horizon_minutes from now (or from `as_of`, a campus-local
    ISO time, for what-if views)."""
    try:
        from digital_twin.prediction.engine import forecast_context
        predictor, basis = forecast_context(get_conn(), as_of)
        result = predictor.predict(lot_id=lot_id, horizon_minutes=horizon_minutes)
        return {
            "lot_id": lot_id,
            "horizon_minutes": horizon_minutes,
            "predicted_fill_rate": round(float(result["fill_rate"]), 4),
            "lower_90": round(float(result["lower_90"]), 4),
            "upper_90": round(float(result["upper_90"]), 4),
            "model": result["model"],
            "proactive_alert": bool(result["fill_rate"] >= 0.90),
            "forecast_basis": basis,
            "data_source": _data_source_label("Trained on"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


@app.get("/predict/all", tags=["Prediction"])
def predict_all_lots(horizon_minutes: int = 15, as_of: Optional[str] = None):
    """Predict occupancy for all VIT-AP parking lots. Follows the campus clock (synthetic daily pattern),
    adjusted by recent live occupancy where it exists; `as_of` shows the pattern for another time."""
    lot_ids = [
        "vitap-lot-academic-main",
        "vitap-lot-hostel",
        "vitap-lot-admin-visitor",
        "vitap-lot-sports",
        "vitap-lot-overflow",
    ]
    try:
        from digital_twin.prediction.engine import forecast_context
        from digital_twin.prediction.engine import data_description
        predictor, basis = forecast_context(get_conn(), as_of)
        real = set(data_description()["real_lots"])
        predictions = []
        for lot_id in lot_ids:
            r = predictor.predict(lot_id=lot_id, horizon_minutes=horizon_minutes)
            predictions.append({
                "lot_id": lot_id,
                "predicted_fill_rate": round(float(r["fill_rate"]), 4),
                "lower_90": round(float(r["lower_90"]), 4),
                "upper_90": round(float(r["upper_90"]), 4),
                "proactive_alert": bool(r["fill_rate"] >= 0.90),
                "model": r.get("model", "unknown"),
                "live_fill_used": bool(r.get("basis", {}).get("live_fill_used")),
                "trained_on": "real" if lot_id in real else "synthetic",
            })
        return {
            "horizon_minutes": horizon_minutes,
            "forecast_basis": basis,
            "predictions": predictions,
            "data_source": _data_source_label("XGBoost model"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {e}")


# ── Risk endpoints ─────────────────────────────────────────────────────────────

@app.get("/risk/current", tags=["Risk"])
def get_current_risk():
    """Return current risk scores across all risk dimensions."""
    try:
        from digital_twin.risk.engine import RiskEngine
        conn = get_conn()
        re = RiskEngine(conn)
        scores = re.compute_all()
        return {"status": "ok", "risks": scores}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk computation failed: {e}")


@app.get("/risk/forecast", tags=["Risk"])
def get_risk_forecast(horizon: int = 15, as_of: Optional[str] = None):
    """Return forecasted risk scores at horizon minutes ahead (time-aware, like /predict/all)."""
    try:
        from digital_twin.risk.engine import RiskEngine
        from digital_twin.prediction.engine import forecast_context
        conn = get_conn()
        predictor, basis = forecast_context(conn, as_of)
        re = RiskEngine(conn, predictor=predictor)
        scores = re.compute_forecast(horizon_minutes=horizon)
        return {"horizon_minutes": horizon, "forecast_basis": basis, "risks": scores}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Risk forecast failed: {e}")


# ── Optimization endpoints ─────────────────────────────────────────────────────

@app.get("/optimize/profiles", tags=["Optimization"])
def optimize_profiles():
    """The weight profiles (P1/P2/P3) with their real weights, so the UI never keeps its own copy."""
    from digital_twin.optimization.engine import describe_profiles
    return {"profiles": describe_profiles()}


@app.post("/optimize", tags=["Optimization"])
def optimize(req: OptimizeRequest):
    try:
        import time as _time
        from digital_twin.optimization.engine import MultiObjectiveOptimizer
        conn = get_conn()
        opt = MultiObjectiveOptimizer(weight_profile=req.weight_profile)
        t0 = _time.perf_counter()
        recommendations = opt.generate_recommendations(conn)
        latency_ms = round((_time.perf_counter() - t0) * 1000, 2)
        return {
            "scenario": req.scenario,
            "weight_profile": req.weight_profile,
            "latency_ms": latency_ms,
            "fallback_used": any(r.get("type") == "FALLBACK" for r in recommendations),
            "recommendations": recommendations,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Optimization failed: {e}")


@app.get("/recommendations", tags=["Optimization"])
def get_recommendations():
    """Get latest proactive parking recommendations."""
    try:
        import time as _time
        from digital_twin.optimization.engine import MultiObjectiveOptimizer
        conn = get_conn()
        opt = MultiObjectiveOptimizer()
        t0 = _time.perf_counter()
        recs = opt.generate_recommendations(conn)
        latency_ms = round((_time.perf_counter() - t0) * 1000, 2)
        return {"recommendations": recs, "count": len(recs), "latency_ms": latency_ms}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Recommendations failed: {e}")


# ── Experiments endpoints ──────────────────────────────────────────────────────

class ExperimentRunRequest(BaseModel):
    scenario: str
    strategies: List[str] = ["B1", "B2", "B3", "P"]
    seeds: List[int] = [0, 1, 2]


def _load_results() -> list:
    if not RESULTS_FILE.exists():
        return []
    try:
        return json.loads(RESULTS_FILE.read_text())
    except Exception:
        return []


def _compute_summary(results: list) -> dict:
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        if r.get("status") == "ok":
            groups[(r["scenario"], r["strategy"])].append(r)

    summary = {}
    for (sc, st), runs in groups.items():
        key = f"{sc}|{st}"
        metrics = {}
        for metric in ["avg_search_time_min", "avg_wait_time_min", "avg_gate_queue",
                        "overflow_events", "successful_park_rate"]:
            vals = [r[metric] for r in runs if r.get(metric) is not None]
            if not vals:
                metrics[metric] = None
                continue
            n = len(vals)
            mean = statistics.mean(vals)
            std = statistics.stdev(vals) if n > 1 else 0.0
            tc = 2.0 if n < 30 else 1.96
            metrics[metric] = {
                "mean": round(mean, 4), "std": round(std, 4),
                "ci95": round(tc * std / math.sqrt(n), 4), "n": n,
            }
        summary[key] = {"scenario": sc, "strategy": st, "n": len(runs), "metrics": metrics}
    return summary


@app.get("/experiments/results", tags=["Experiments"])
def get_experiment_results(
    scenario: Optional[str] = None,
    strategy: Optional[str] = None,
    limit: int = 200,
):
    """Return stored experiment run records, optionally filtered."""
    results = _load_results()
    if not results:
        return {"results": [], "total": 0, "note": "No results found. Run experiments first."}

    if scenario:
        results = [r for r in results if r.get("scenario") == scenario]
    if strategy:
        results = [r for r in results if r.get("strategy") == strategy]

    return {
        "results": results[:limit],
        "total": len(results),
        "returned": min(len(results), limit),
        "data_source": "experiments/results/all_results.json",
    }


@app.get("/experiments/summary", tags=["Experiments"])
def get_experiment_summary():
    """Return aggregated stats (mean ± 95%CI) per scenario × strategy."""
    # Prefer pre-computed file; recompute if absent or if all_results is newer
    if SUMMARY_FILE.exists():
        try:
            return json.loads(SUMMARY_FILE.read_text())
        except Exception:
            pass
    results = _load_results()
    if not results:
        return {}
    return _compute_summary(results)


@app.post("/experiments/run", tags=["Experiments"])
def run_experiment(req: ExperimentRunRequest):
    """
    Run a small experiment batch synchronously (≤ 5 seeds recommended).
    Results are appended to experiments/results/all_results.json.
    """
    import time as _time

    STRATEGY_MAP = {
        "B1": ("B1", lambda: __import__("digital_twin.simulation.strategy",
                fromlist=["FirstAvailableStrategy"]).FirstAvailableStrategy()),
        "B2": ("B2", lambda: __import__("digital_twin.simulation.strategy",
                fromlist=["NearestAvailableStrategy"]).NearestAvailableStrategy()),
        "B3": ("B3", lambda: __import__("digital_twin.simulation.demo_strategies",
                fromlist=["PredictionOnlyStrategy"]).PredictionOnlyStrategy()),
        "P":  ("P",  lambda: __import__("digital_twin.simulation.demo_strategies",
                fromlist=["ParkingNavXFullStrategy"]).ParkingNavXFullStrategy()),
    }

    scenario_file = SCENARIO_DIR / f"{req.scenario}.yaml"
    if not scenario_file.exists():
        raise HTTPException(status_code=404, detail=f"Scenario '{req.scenario}' not found")

    bad_strats = [s for s in req.strategies if s not in STRATEGY_MAP]
    if bad_strats:
        raise HTTPException(status_code=400, detail=f"Unknown strategies: {bad_strats}")

    new_results = []
    for strategy_code in req.strategies:
        label, factory = STRATEGY_MAP[strategy_code]
        for seed in req.seeds:
            run_id = f"{req.scenario}-{strategy_code}-s{seed}"
            conn = get_conn()
            strategy = factory()
            strategy.label = label
            sc = ScenarioLoader.load(scenario_file)
            sc.random_seed = seed
            t0 = _time.time()
            try:
                engine = SimulationEngine()
                result = engine.run(sc, strategy, conn, run_id=run_id)
                m = result.metrics
                rec = {
                    "run_id": run_id, "scenario": req.scenario,
                    "strategy": strategy_code, "seed": seed,
                    "elapsed_s": round(_time.time() - t0, 2),
                    "avg_search_time_min": m.get("avg_search_time_min"),
                    "avg_wait_time_min": m.get("avg_wait_time_min"),
                    "avg_gate_queue": m.get("avg_gate_queue"),
                    "overflow_events": m.get("overflow_events_count"),
                    "total_vehicles": m.get("total_vehicles"),
                    "successful_park_rate": m.get("successful_park_rate"),
                    "status": "ok",
                }
            except Exception as e:
                rec = {"run_id": run_id, "scenario": req.scenario,
                       "strategy": strategy_code, "seed": seed,
                       "error": str(e), "status": "error"}
            new_results.append(rec)

    # Persist
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_results()
    by_id = {r["run_id"]: r for r in existing}
    for r in new_results:
        by_id[r["run_id"]] = r
    RESULTS_FILE.write_text(json.dumps(list(by_id.values()), indent=2))

    ok = [r for r in new_results if r.get("status") == "ok"]
    err = [r for r in new_results if r.get("status") == "error"]
    return {
        "submitted": len(new_results),
        "ok": len(ok),
        "errors": len(err),
        "results": new_results,
    }
