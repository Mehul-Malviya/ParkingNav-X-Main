# ParkingNav-X — API Reference

**Base URL:** `http://localhost:8000`  
**OpenAPI docs:** `http://localhost:8000/docs`  
**Version:** 2.0.0  
**Framework:** FastAPI + SQLite

All responses are JSON. All data is synthetic unless stated otherwise.

---

## Campus

### GET `/`
System info and version.

**Response:**
```json
{"name": "ParkingNav-X", "version": "2.0.0", "status": "ok"}
```

### GET `/campus`
Campus summary: gate count, lot count, total capacity, destination count.

**Response:**
```json
{"campus_id": "vitap", "gates": 2, "lots": 5, "total_capacity": 540, "destinations": 17}
```

### GET `/campus/graph`
Full campus graph: nodes (gates, lots, intersections, destinations) and weighted edges.

**Response:**
```json
{
  "nodes": [{"id": "vitap-gate-main", "type": "gate", "x": 450, "y": 120}, ...],
  "edges": [{"from": "vitap-gate-main", "to": "vitap-lot-academic-main", "cost": 120}, ...]
}
```

### GET `/scenarios`
List of available simulation scenario YAML stems.

**Response:**
```json
{"scenarios": ["E1_normal_day", "E2_event_placement", "E3_lot_closure", ...]}
```

### GET `/strategies`
Available strategy codes and descriptions.

**Response:**
```json
{
  "strategies": {
    "B1": "First Available — assigns first lot with space",
    "B2": "Nearest Available — closest lot by travel cost",
    "B3": "Prediction Only — avoids forecast-critical lots",
    "P":  "ParkingNav-X Full — prediction + optimization + proactive"
  }
}
```

### GET `/events`
Campus events loaded from `data/vitap_events.csv`.

**Response:**
```json
{"events": [{"event_id": "placement_drive_2026", "type": "placement_drive", "intensity": 1.0}]}
```

---

## Simulation

### POST `/simulate`
Run a simulation scenario with a chosen strategy.

**Request body:**
```json
{"scenario": "E2_event_placement", "strategy": "P"}
```

- `scenario`: YAML stem from `configs/scenarios/vitap/` (default: `E1_normal_day`)
- `strategy`: one of `B1`, `B2`, `B3`, `P` (default: `"P"`)

**Response:**
```json
{
  "scenario": "E2_event_placement",
  "strategy": "P",
  "metrics": {
    "total_vehicles": 400,
    "total_ever_parked": 395,
    "successful_park_rate": 0.9875,
    "overflow_events_count": 2,
    "avg_search_time_min": 3.2,
    "avg_wait_time_min": 1.1,
    "avg_gate_queue": 4.5,
    "max_gate_queue": 12
  },
  "run_id": "E2_event_placement-P-s0"
}
```

**Error:** `400` if scenario or strategy is invalid.

### GET `/compare/{scenario}`
Run all 4 strategies (B1, B2, B3, P) on the same scenario and compare metrics.

**Path param:** `scenario` — YAML stem (e.g. `E1_normal_day`)

**Response:**
```json
{
  "scenario": "E1_normal_day",
  "results": {
    "B1": {"avg_search_time_min": 5.4, ...},
    "B2": {"avg_search_time_min": 4.1, ...},
    "B3": {"avg_search_time_min": 3.8, ...},
    "P":  {"avg_search_time_min": 3.2, ...}
  }
}
```

---

## Routing

### GET `/route`
Shortest path between two campus nodes.

**Query params:** `origin` (node ID), `destination` (node ID), `mode` (default: `drive`)

**Response:**
```json
{
  "origin": "vitap-gate-main",
  "destination": "vitap-lot-academic-main",
  "path": ["vitap-gate-main", "vitap-intersection-1", "vitap-lot-academic-main"],
  "cost_seconds": 95
}
```

**Error:** `404` if no path exists.

### GET `/find_parking`
Ranked parking options for a destination, ordered by predicted availability and travel cost.

**Query params:** `destination_id`, `gate_id` (default: `vitap-gate-main`)

**Response:**
```json
{
  "destination_id": "vitap-dest-ab1",
  "options": [
    {"lot_id": "vitap-lot-academic-main", "travel_cost": 95, "forecast_fill": 0.62, "recommended": true},
    {"lot_id": "vitap-lot-admin-visitor", "travel_cost": 180, "forecast_fill": 0.41, "recommended": true}
  ]
}
```

---

## Prediction

### GET `/predict/occupancy`
Predict occupancy for a single lot at a given horizon.

**Query params:** `lot_id`, `horizon_minutes` (default: 15)

**Response:**
```json
{
  "lot_id": "vitap-lot-academic-main",
  "horizon_minutes": 15,
  "model": "XGBoost",
  "predicted_fill_rate": 0.74,
  "lower_90": 0.69,
  "upper_90": 0.79,
  "data_provenance": "[SYNTHETIC]"
}
```

### GET `/predict/all`
Predict occupancy for all 5 lots.

**Query params:** `horizon_minutes` (default: 15)

**Response:**
```json
{
  "horizon_minutes": 15,
  "predictions": [
    {"lot_id": "vitap-lot-academic-main", "predicted_fill_rate": 0.74, "lower_90": 0.69, "upper_90": 0.79},
    ...
  ],
  "model": "XGBoost",
  "data_provenance": "[SYNTHETIC]"
}
```

---

## Risk

### GET `/risk/current`
Current risk scores for all lots and gates, based on the most recent simulation output.

**Response:**
```json
{
  "risks": {
    "vitap-lot-academic-main": {"overflow_risk": 0.72, "level": "HIGH"},
    "vitap-gate-main": {"queue_risk": 0.31, "level": "MEDIUM"}
  }
}
```

### GET `/risk/forecast`
Forecast risk scores at a given horizon using predicted occupancy.

**Query params:** `horizon_minutes` (default: 15)

**Response:**
```json
{"horizon_minutes": 15, "risks": {"vitap-lot-academic-main": {"overflow_risk": 0.88, "level": "CRITICAL"}}}
```

---

## Optimization

### POST `/optimize`
Generate recommendations using a specific weight profile.

**Request body:**
```json
{"scenario": "E2_event_placement", "weight_profile": "P1"}
```

- `weight_profile`: `P1` (minimize waiting), `P2` (balanced), `P3` (minimize overflow)

**Response:**
```json
{
  "scenario": "E2_event_placement",
  "weight_profile": "P1",
  "recommendations": [
    {
      "type": "LOT_RANKING",
      "recommended_lot": "vitap-lot-admin-visitor",
      "objective_score": 0.312,
      "why_chosen": "Chosen because Admin / Visitor Parking has the lowest objective score (0.312) among 3 feasible alternatives.",
      "alternatives": [...],
      "cost_function": {"J": 0.312, "waiting_time": 0.15, ...}
    }
  ]
}
```

### GET `/recommendations`
Latest proactive recommendations (uses P1 weight profile).

Same response shape as `/optimize`. Includes `PROACTIVE_REROUTE` alerts when forecast > 90% AND current < 90%.

---

## Experiments

### GET `/experiments/results`
Stored experiment run records.

**Query params:** `scenario` (optional), `strategy` (optional), `limit` (default: 200)

**Response:**
```json
{
  "results": [
    {
      "run_id": "E1_normal_day-P-s0",
      "scenario": "E1_normal_day",
      "strategy": "P",
      "seed": 0,
      "avg_search_time_min": 3.2,
      "avg_wait_time_min": 1.1,
      "overflow_events": 0,
      "successful_park_rate": 0.99,
      "status": "ok"
    }
  ],
  "total": 1,
  "returned": 1
}
```

**Note:** Returns empty list with `note` field if no experiments have been run yet.

### GET `/experiments/summary`
Aggregated statistics per scenario × strategy with 95% CI.

**Response:**
```json
{
  "E1_normal_day|P": {
    "scenario": "E1_normal_day",
    "strategy": "P",
    "n": 30,
    "metrics": {
      "avg_search_time_min": {"mean": 3.21, "std": 0.42, "ci95": 0.15, "n": 30}
    }
  }
}
```

### POST `/experiments/run`
Run a small experiment batch synchronously (≤5 seeds recommended for API use).

**Request body:**
```json
{"scenario": "E1_normal_day", "strategies": ["B1", "B2", "P"], "seeds": [0, 1, 2]}
```

**Response:**
```json
{"submitted": 9, "ok": 9, "errors": 0, "results": [...]}
```

Results are appended to `experiments/results/all_results.json` and deduplicated by `run_id`.

---

## Error responses

All endpoints return structured errors:

```json
{"detail": "Scenario 'nonexistent' not found"}   // 404
{"detail": "Unknown strategies: ['X']"}           // 400
{"error": "...", "recommendations": []}            // 500 (non-fatal, returns empty)
```
