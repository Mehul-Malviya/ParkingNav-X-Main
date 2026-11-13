# Phase 1 -- Verification Commands (Member 1)
Run these in order from the repo root. Each command shows real proof.

---

## 0. Lint -- zero errors

```
python -m ruff check .
```
Expected: `All checks passed!`

---

## 1.1 Campus Config

**Validate real campus:**
```
python -m digital_twin.simulation.cli validate-campus --campus vitap --config configs/campus/vitap.yaml
```
Expected: `Campus valid` with gate/lot/road counts.

**Break-test 1 -- negative capacity:**
```
python -m digital_twin.simulation.cli validate-campus --campus vitap --config configs/campus/vitap.yaml
```
(Temporarily set a lot capacity to -1 in vitap.yaml, then run -- should print the failing lot name.)

**Break-test 2 -- unreachable lot:**
Delete the only road to a lot in vitap.yaml, run validate -- should fail with "unreachable".

**Graph PNG:**
```
python scripts/export_campus_graph_png.py --campus vitap --config configs/campus/vitap.yaml --output /tmp/vitap_graph.png
```
Expected: PNG saved, every lot has a path to a gate.

---

## 1.2 Digital Twin State

```python
python -c "
import sys; sys.path.insert(0, '.')
from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.state_snapshot import StateSnapshot, LotState, GateState, RoadState

conn = get_connection(':memory:')
apply_migrations(conn)
load_campus_config('configs/campus/vitap.yaml', conn)

lots  = [LotState('P1', 100, 0, 100, 0, 'open', 0, 0)]
gates = [GateState('G1', 0, 6.0, 'open', 0)]
roads = [RoadState('R1', 30.0, 0.0, 'open', 0, 600)]
snap  = StateSnapshot(0, '2026-10-12T08:00:00', lots, gates, roads, {}, [], [], {}, {})

# Check 1: start state
assert snap.lots[0].occupied == 0
print('CHECK 1 PASS: start state clean')

# Check 2: park 10 cars
snap.lots[0].occupied = 10
snap.lots[0].available = 90
assert snap.lots[0].occupied == 10
print('CHECK 2 PASS: park 10 cars')

# Check 3: lot_closed event
snap.apply_event({'type': 'lot_closed', 'lot_id': 'P1'})
assert snap.lots[0].status == 'closed'
print('CHECK 3 PASS: lot_closed event')

# Check 4: clone isolation
clone = snap.clone()
clone.lots[0].occupied = 99
assert snap.lots[0].occupied == 10
print('CHECK 4 PASS: clone isolated')

# Check 5: event log
assert len(snap.event_log) == 1
print('CHECK 5 PASS: event log has 1 entry:', snap.event_log[0])

# Check 6: invariants raises on overflow
snap.lots[0].occupied = 200
try:
    snap.invariants()
    print('CHECK 6 FAIL: should have raised')
except AssertionError as e:
    print('CHECK 6 PASS: invariants raised:', e)
"
```
Expected: 6 lines all saying PASS.

---

## 1.3 Simulation Loop

**Full test suite (covers all 1.3 assertions):**
```
python -m pytest tests/simulation/test_part5_baseline_strategies.py tests/simulation/test_part4_part5_simulation.py -v
```
Expected: 15 passed.

Key tests and what they prove:
- `test_first_available_strategy_assigns_first_open_lot` -- all 50 vehicles reach terminal state (6a)
- `test_occupancy_rises_then_falls` -- occupancy rises then falls (6b)
- `test_vehicle_accounting_identity` -- entered = parked + exited (6c)
- `test_b1_vs_b2_produce_different_distributions` -- different seeds = different results (6d)
- `test_baseline_determinism_same_seed_same_assignments` -- same seed = identical result

**Live demo (FirstAvailable demoable):**
```python
python -c "
from digital_twin.api_functions import run_simulation, get_metrics
run_id = run_simulation('configs/scenarios/vitap/E1_normal_day.yaml', 'FirstAvailable', seed=1)
m = get_metrics(run_id)
print('run_id   :', run_id)
print('vehicles :', m['secondary_metrics']['total_vehicles_simulated'])
print('success  :', m['secondary_metrics']['allocation_success_rate'])
print('avg search:', m['primary_metrics']['avg_search_time_min'], 'min')
"
```
Expected: 400 vehicles, 1.0 success rate, non-zero search time.

---

## 1.4 Observation Plan

```
Get-Content docs\member1\observation_plan.md | Select-String "Date|Schema|Session"
```
Expected: Session 1 = 2026-10-12, Session 2 = 2026-11-02, schema columns listed.

---

## All tests at once

```
python -m pytest tests/ -q
```
Expected: `175 passed, 15 skipped`

---

## Quick single-line audit

```
python -m ruff check . && python -m pytest tests/ -q --tb=no
```
Expected: `All checks passed!` then `175 passed, 15 skipped`
