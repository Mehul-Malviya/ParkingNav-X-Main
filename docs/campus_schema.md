# Campus Configuration Schema

**Derived from:** `digital_twin/config_loader.py` — `_validate_db_schema()` and `_validate_simulation_schema()`  
**Last updated:** October 2026  
**Load command:** `python -m digital_twin.simulation.cli validate-campus --campus <id>`

---

## Overview

A campus is described by a single YAML file at `configs/campus/<campus_id>.yaml`.
Loading a new campus requires **zero code changes** — the loader reads everything from YAML and
validates it before writing anything to SQLite.

Two YAML schema variants are supported and auto-detected:

| Variant | When used | Key field |
|---|---|---|
| **DB schema** | Production (vitap, sample, toy_small) | `campus.campus_id`, `parking_lots`, `edges` |
| **Simulation schema** | Older/alternative format | `campus.id`, `lots`, `roads` with `from`/`to`/`length_m` |

The vitap.yaml and toy_small.yaml use the **DB schema**. Everything below describes the DB schema.

---

## Top-Level Structure

```yaml
campus:       # required — campus metadata
gates:        # required — at least one
parking_lots: # required — at least one
destinations: # optional
roads:        # optional — geometry of each road
edges:        # optional — graph connectivity
events:       # optional — scheduled events
```

---

## `campus` block (required)

| Field | Type | Required | Notes |
|---|---|---|---|
| `campus_id` | string | ✅ | Unique identifier. Used as FK for all entities. |
| `name` | string | ✅ | Human-readable name. |
| `description` | string | — | Free text. |
| `timezone` | string | — | e.g. `Asia/Kolkata`. Defaults to `UTC`. |
| `configuration_version` | string | — | Version tag stored in DB. |

---

## `gates` (required — at least one)

| Field | Type | Required | Validation rule |
|---|---|---|---|
| `gate_id` | string | ✅ | Must be unique within the file. Doubles as a graph node id. |
| `name` | string | ✅ | |
| `latitude` | float | ✅ | Must be in range −90 to 90. |
| `longitude` | float | ✅ | Must be in range −180 to 180. |
| `capacity` | int | ✅ | **Must be > 0.** Fails: `"Gate 'X' has non-positive capacity."` |
| `status` | string | — | `open` or `closed`. Defaults to `open`. |
| `metadata` | dict | — | Stored as JSON. Any extra fields. |

---

## `parking_lots` (required — at least one)

| Field | Type | Required | Validation rule |
|---|---|---|---|
| `parking_lot_id` | string | ✅ | Must be unique within the file. Doubles as a graph node id. |
| `name` | string | ✅ | |
| `latitude` | float | ✅ | Range −90 to 90. |
| `longitude` | float | ✅ | Range −180 to 180. |
| `total_capacity` | int | ✅ | **Must be > 0.** Fails: `"ParkingLot 'X' has non-positive total_capacity."` |
| `usable_capacity` | int | ✅ | |
| `reserved_capacity` | int | — | Defaults to 0. |
| `restricted_capacity` | int | — | Defaults to 0. |
| `temporarily_unavailable_capacity` | int | — | Defaults to 0. |
| `status` | string | — | `open` or `closed`. Defaults to `open`. |
| `zone` | string | — | Free label. |
| `boundary_polygon` | string | — | WKT polygon. |

**Capacity invariant (enforced):** `usable + reserved + restricted + temporarily_unavailable ≤ total_capacity`  
Fails: `"ParkingLot 'X': usable+reserved+restricted+unavailable exceeds total_capacity."`

---

## `destinations` (optional)

| Field | Type | Required | Validation rule |
|---|---|---|---|
| `destination_id` | string | ✅ | Must be unique. Doubles as a graph node id. |
| `name` | string | ✅ | |
| `category` | string | — | e.g. `academic_block`, `hostel`. Defaults to `other`. |
| `latitude` | float | — | Range −90 to 90. |
| `longitude` | float | — | Range −180 to 180. |
| `nearest_gate_ids` | list[string] | — | Each id **must exist** in `gates`. Fails: `"Destination 'X' references unknown gate 'Y'."` |
| `nearest_parking_lot_ids` | list[string] | — | Each id **must exist** in `parking_lots`. Fails: `"Destination 'X' references unknown parking lot 'Y'."` |

---

## `roads` (optional but recommended for geometry)

| Field | Type | Required | Validation rule |
|---|---|---|---|
| `road_id` | string | ✅ | Must be unique. |
| `name` | string | ✅ | |
| `start_node_id` | string | ✅ | **Must exist** in gates/lots/destinations. Fails: `"Road 'X' start_node_id 'Y' does not exist."` |
| `end_node_id` | string | ✅ | **Must exist** in gates/lots/destinations. Fails: `"Road 'X' end_node_id 'Y' does not exist."` |
| `length_meters` | float | ✅ | **Must be > 0.** Fails: `"Road 'X' has non-positive length_meters."` |
| `expected_travel_time_seconds` | float | — | |
| `is_walkable` | bool | — | Defaults to `true`. |
| `is_driveable` | bool | — | Defaults to `true`. |
| `status` | string | — | `open` or `closed`. |
| `geometry` | list[{lat, lng}] | ✅ | **Must have ≥ 3 points** (start + at least 1 intermediate + end). A straight line (2 points) is rejected: `"Road 'X' geometry has only its two endpoints; a straight line cannot represent a real curved path."` First point must match `start_node_id` coords; last must match `end_node_id` coords. |

---

## `edges` (optional — graph connectivity)

Defines the routing graph. Each edge is a directed connection between two nodes.

| Field | Type | Required | Validation rule |
|---|---|---|---|
| `from_node_id` | string | ✅ | **Must exist** in known nodes. Fails: `"Edge references unknown from_node_id 'X'."` |
| `to_node_id` | string | ✅ | **Must exist** in known nodes. Fails: `"Edge references unknown to_node_id 'X'."` |
| `road_id` | string | — | Reference to a road for metadata lookup. |
| `weight_time_seconds` | float | ✅ | Used by NetworkX shortest-path (`weight="weight_time_seconds"`). |
| `weight_distance_meters` | float | ✅ | Used by NetworkX shortest-path (`weight="weight_distance_meters"`). |
| `is_walkable` | bool | — | |
| `is_driveable` | bool | — | |
| `status` | string | — | `open` or `closed`. |

**Orphan node rule:** Every node (gate, lot, destination) referenced anywhere **must appear in at least one edge**.  
Fails: `"Node 'X' is not connected by any edge in ROUTES_GRAPH_EDGES (orphan node)."`

For bidirectional roads, add **two edges** (A→B and B→A) explicitly.

---

## `events` (optional)

| Field | Type | Required | Notes |
|---|---|---|---|
| `event_id` | string | ✅ | Must be unique. |
| `event_type` | string | ✅ | e.g. `exam`, `placement`, `fest`. |
| `name` | string | ✅ | |
| `start_time` | ISO8601 string | — | |
| `end_time` | ISO8601 string | — | |
| `expected_demand_multiplier` | float | — | Defaults to 1.0. |
| `affected_zones` | list or string | — | |
| `status` | string | — | `scheduled`, `active`, `completed`. |

Events can also be loaded from `data/<campus_id>_events.csv` automatically.

---

## Full Validation Summary

Run the validator at any time:
```
python -m digital_twin.simulation.cli validate-campus --campus vitap
python -m digital_twin.simulation.cli validate-campus --campus toy_small
```

All rules that fail are reported together — the loader never silently fixes anything.
If any rule fails, **nothing is written to the database**.

### Rules that cause hard failure

1. Missing `campus_id`
2. No gates defined
3. No lots defined  
4. Duplicate IDs (any entity type)
5. Gate capacity ≤ 0 — names the gate
6. Lot total_capacity ≤ 0 — names the lot
7. Lot capacity invariant violated — names the lot
8. Road length ≤ 0 — names the road
9. Road `start_node_id` or `end_node_id` does not exist — names the road and the missing node
10. Road geometry has < 3 points or geometry endpoints don't match node coordinates
11. Edge references unknown node — names the edge and the missing node
12. Node not connected by any edge (orphan) — names the node
13. Destination references unknown gate or lot — names the destination and missing id
14. Latitude/longitude out of range — names the entity

---

## Adding a New Campus (Zero Code Changes)

1. Copy `configs/campus/toy_small.yaml` as a starting point.
2. Set a unique `campus_id`.
3. Add gates, lots, destinations, roads, edges.
4. Run `validate-campus` until it prints "Campus valid".
5. Reference the new `campus_id` in scenario YAMLs under `configs/scenarios/<campus_id>/`.
