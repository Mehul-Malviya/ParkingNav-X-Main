"""
Standalone verification for Part 1 (M1) — Campus Configuration.

Run: python -m digital_twin.simulation.verify_campus_config
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import yaml
from pydantic import ValidationError

from digital_twin.simulation.campus_config import (
    CampusConfig,
    build_digraph,
    load_campus,
    plot_campus,
)

PASS = "[PASS]"
FAIL = "[FAIL]"


def check(label: str, passed: bool, detail: str = "") -> None:
    mark = PASS if passed else FAIL
    msg = f"{mark} {label}"
    if detail:
        msg += f"\n       {detail}"
    print(msg)
    if not passed:
        sys.exit(1)


# ── Test 1: load vitap (main campus) ─────────────────────────────────────────
print("\n=== Test 1: load vitap ===")
try:
    campus = load_campus("vitap", str(ROOT / "configs" / "campus"))
    detail = (
        f"id={campus.id} | gates={len(campus.gates)} | lots={len(campus.parking_lots)} "
        f"| roads={len(campus.roads)} | nodes={len(campus.nodes)}"
    )
    check("vitap loads and validates", True, detail)
    print(f"       Campus valid — '{campus.id}' | {len(campus.gates)} gates | "
          f"{len(campus.parking_lots)} lots | {len(campus.roads)} roads | {len(campus.nodes)} nodes")
except Exception as exc:
    check("vitap loads and validates", False, str(exc))


# ── Test 2: load toy_small (v1 spec schema file) ──────────────────────────────
print("\n=== Test 2: load toy_small (spec schema) ===")
try:
    campus2 = load_campus("toy_small", str(ROOT / "configs" / "campus"))
    detail2 = (
        f"id={campus2.id} | gates={len(campus2.gates)} | lots={len(campus2.parking_lots)} "
        f"| roads={len(campus2.roads)} | nodes={len(campus2.nodes)}"
    )
    check("toy_small loads and validates", True, detail2)
    print(f"       Campus valid — '{campus2.id}' | {len(campus2.gates)} gates | "
          f"{len(campus2.parking_lots)} lots | {len(campus2.roads)} roads | {len(campus2.nodes)} nodes")
except Exception as exc:
    check("toy_small loads and validates", False, str(exc))


# ── Test 3: negative capacity → ValidationError naming the lot ───────────────
print("\n=== Test 3: negative capacity -> ValidationError ===")
BAD_CAPACITY_YAML = """
id: bad_campus
name: Bad Campus
time_step_sec: 10
nodes:
  - {id: G1, type: gate, lat: 0.0, lon: 0.0, name: Gate}
  - {id: J1, type: junction, lat: 0.1, lon: 0.1, name: Junction}
  - {id: P1_IN, type: lot_entrance, lat: 0.2, lon: 0.2, name: Lot Entrance}
gates:
  - {id: G1, node: G1, service_rate_vph: 120, lanes: 1, status: open}
roads:
  - {id: R1, from: G1, to: J1, length_m: 100, free_speed_kmph: 20, capacity_vph: 200, status: open}
  - {id: R2, from: J1, to: P1_IN, length_m: 50, free_speed_kmph: 15, capacity_vph: 100, status: open}
parking_lots:
  - {id: BAD_LOT, entrance_node: P1_IN, capacity: -10, reserved: {accessible: 0, staff: 0},
     zone: Z1, status: open}
zones:
  - id: Z1
    name: Zone 1
    nearest_nodes: [J1]
    walk_time_to_lot_sec: {BAD_LOT: 60}
event_types: [normal]
"""
try:
    CampusConfig.model_validate(yaml.safe_load(BAD_CAPACITY_YAML))
    check("negative capacity raises ValidationError", False, "Expected ValidationError but none raised")
except ValidationError as exc:
    msg = str(exc)
    names_lot = "BAD_LOT" in msg
    check(
        "negative capacity raises ValidationError naming 'BAD_LOT'",
        names_lot,
        f"Error snippet: {msg[:300]}"
    )
except Exception as exc:
    check("negative capacity raises ValidationError", False, f"Wrong exception: {exc}")


# ── Test 4: bad road node → ValidationError naming the road ──────────────────
print("\n=== Test 4: bad road node reference -> ValidationError ===")
BAD_ROAD_YAML = """
id: bad_road_campus
name: Bad Road Campus
time_step_sec: 10
nodes:
  - {id: G1, type: gate, lat: 0.0, lon: 0.0, name: Gate}
  - {id: J1, type: junction, lat: 0.1, lon: 0.1, name: Junction}
  - {id: P1_IN, type: lot_entrance, lat: 0.2, lon: 0.2, name: Lot Entrance}
gates:
  - {id: G1, node: G1, service_rate_vph: 120, lanes: 1, status: open}
roads:
  - {id: ROAD_BAD, from: G1, to: NONEXISTENT_NODE, length_m: 100, free_speed_kmph: 20, capacity_vph: 200, status: open}
  - {id: R2, from: G1, to: J1, length_m: 100, free_speed_kmph: 20, capacity_vph: 200, status: open}
  - {id: R3, from: J1, to: P1_IN, length_m: 50, free_speed_kmph: 15, capacity_vph: 100, status: open}
parking_lots:
  - {id: P1, entrance_node: P1_IN, capacity: 50, reserved: {accessible: 0, staff: 0},
     zone: Z1, status: open}
zones:
  - id: Z1
    name: Zone 1
    nearest_nodes: [J1]
    walk_time_to_lot_sec: {P1: 60}
event_types: [normal]
"""
try:
    CampusConfig.model_validate(yaml.safe_load(BAD_ROAD_YAML))
    check("bad road node raises ValidationError", False, "Expected ValidationError but none raised")
except ValidationError as exc:
    msg = str(exc)
    names_road = "ROAD_BAD" in msg
    check(
        "bad road node raises ValidationError naming 'ROAD_BAD'",
        names_road,
        f"Error snippet: {msg[:300]}"
    )
except Exception as exc:
    check("bad road node raises ValidationError", False, f"Wrong exception: {exc}")


# ── Test 5: unreachable lot → ValidationError ─────────────────────────────────
print("\n=== Test 5: unreachable lot -> ValidationError ===")
UNREACHABLE_YAML = """
id: unreachable_campus
name: Unreachable Campus
time_step_sec: 10
nodes:
  - {id: G1, type: gate, lat: 0.0, lon: 0.0, name: Gate}
  - {id: J1, type: junction, lat: 0.1, lon: 0.1, name: Junction}
  - {id: P1_IN, type: lot_entrance, lat: 0.2, lon: 0.2, name: P1 Entrance}
  - {id: P3_IN, type: lot_entrance, lat: 0.5, lon: 0.5, name: P3 Entrance (isolated)}
gates:
  - {id: G1, node: G1, service_rate_vph: 120, lanes: 1, status: open}
roads:
  - {id: R1, from: G1, to: J1, length_m: 100, free_speed_kmph: 20, capacity_vph: 200, status: open}
  - {id: R2, from: J1, to: P1_IN, length_m: 50, free_speed_kmph: 15, capacity_vph: 100, status: open}
parking_lots:
  - {id: P1, entrance_node: P1_IN, capacity: 50, reserved: {accessible: 0, staff: 0},
     zone: Z1, status: open}
  - {id: P3, entrance_node: P3_IN, capacity: 30, reserved: {accessible: 0, staff: 0},
     zone: Z1, status: open}
zones:
  - id: Z1
    name: Zone 1
    nearest_nodes: [J1]
    walk_time_to_lot_sec: {P1: 60, P3: 200}
event_types: [normal]
"""
try:
    CampusConfig.model_validate(yaml.safe_load(UNREACHABLE_YAML))
    check("unreachable lot raises ValidationError", False, "Expected ValidationError but none raised")
except ValidationError as exc:
    msg = str(exc)
    names_p3 = "P3" in msg
    check(
        "unreachable lot raises ValidationError naming 'P3'",
        names_p3,
        f"Error snippet: {msg[:300]}"
    )
except Exception as exc:
    check("unreachable lot raises ValidationError", False, f"Wrong exception: {exc}")


# ── Test 6: graph PNG saved ───────────────────────────────────────────────────
print("\n=== Test 6: graph PNG saved ===")
try:
    campus = load_campus("vitap", str(ROOT / "configs" / "campus"))
    png_path = plot_campus(campus, str(ROOT / "docs" / "campus_graph_vitap.png"))
    exists = Path(png_path).exists()
    check("campus graph PNG saved", exists, f"Saved to: {png_path}")
except Exception as exc:
    check("campus graph PNG saved", False, str(exc))


print("\nALL CHECKS PASSED")
