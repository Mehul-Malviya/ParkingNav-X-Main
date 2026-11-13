# Interfaces to Teammates — Member 1

*** Jyothi Reddy Pula (23BCE7882) · VIT-AP · ParkingNav-X

---

## → Member 2 (Data + ML)

**What I provide — two frozen datasets (both labelled `source=simulated` until real data exists):**

1. **Per-vehicle dataset** (`make_dataset`): one row per vehicle per run.
2. **Timestep CSVs** (`python scripts/generate_member2_dataset.py` -> `data/member2_synthetic/{scenario_id}/`):
   - `lots.csv`: one row per (timestamp, lot) at 5-min resolution. Columns: `scenario_id, seed, timestamp, sim_time_min, lot_id, capacity, occupied_spaces, occupancy_pct, arrivals_5m, departures_5m, day_type, event_type, event_intensity, source`.
   - `gates.csv`: one row per (minute, gate). Columns: `scenario_id, seed, tick, sim_time_min, gate_id, queue_length, source`.

Re-take these files whenever the engine changes (the SEARCHING state and 10 s tick shifted `lots.csv` by a mean of ~1 space; `gates.csv` is unchanged to within 1 vehicle).

**How to generate the per-vehicle dataset:**
```python
from digital_twin.api_functions import make_dataset
make_dataset(
    campus_id="vitap",
    scenario_paths=["configs/scenarios/vitap/E1_normal_day.yaml",
                    "configs/scenarios/vitap/E2_event_placement.yaml"],
    seeds=list(range(30)),
    output_path="data/ml_dataset.csv"
)
```

**Columns:** `scenario_id, seed, arrival_time, assigned_lot_id, search_time_min, wait_time_min, final_state, complied, travel_distance_m`
(`travel_distance_m` = outbound + inbound distance in metres. It was 0 in every row before 2026-10-11; regenerate any older export.)

**Guarantee:** features use only past/current values — no future leakage.

---

## → Member 3 (Optimization)

**What I provide:** `StateSnapshot` JSON (now including per-vehicle `vehicles` with state, timestamps and trace times) + `snapshot.fork()` for look-ahead.

**How to get current state:**
```python
from digital_twin.api_functions import get_state
state = get_state(run_id, tick)
# Returns: {sim_time, sim_time_iso, scenario_id, seed, lots, gates, roads,
#           pending_arrivals_by_gate (next 5 min), active_events, active_disruptions,
#           travel_time_matrix[gate][lot] (s), walk_time ({} - no walking model), forecast,
#           vehicles, event_log}
```
`tick` is in **minutes** since scenario start (the engine itself steps in 10 s ticks; logs are reported per minute, vehicle traces also carry `t_sec`). A lot's `occupied` equals the number of vehicles in SEARCHING or PARKED at that lot (a space is reserved on arrival).

**Fork for what-if:**
```python
from digital_twin.simulation.state_snapshot import StateSnapshot
fork = snapshot.fork()  # deep independent copy — safe to mutate
```

**Plug a strategy in without editing our code:**
```python
from digital_twin.api_functions import register_strategy, run_simulation
register_strategy("MyOptimizer", MyOptimizer)          # zero-arg factory
run_id = run_simulation("configs/scenarios/vitap/E2_event_placement.yaml", "MyOptimizer", seed=0)
```
The engine calls `assign()` per served vehicle (200 ms timeout; exception, timeout or infeasible result falls back to NearestAvailable and is logged) and `update_policy(state, forecast)` every 5 simulated minutes (`forecast=None` until Member 2's predictor is wired in). B3 (PredictionOnly) and P (ParkingNavXFull) are in `demo_strategies.py`.

**Strategy interface** (`digital_twin/simulation/strategy.py`):
```python
class AllocationStrategy(Protocol):
    def assign(self, vehicle, state) -> AssignmentResult: ...
    def update_policy(self, state, forecast) -> None: ...
```

---

## → Member 4 (Platform + Validation)

**What I provide:** pure Python functions for the FastAPI layer.

```python
from digital_twin.api_functions import (
    load_campus,        # load_campus("vitap") -> campus dict
    get_state,          # get_state(run_id, tick) -> StateSnapshot dict
    run_simulation,     # run_simulation(scenario, strategy, seed) -> run_id
    run_batch,          # run_batch(scenario, strategies, seeds) -> [run_id]
    get_metrics,        # get_metrics(run_id) -> {primary_metrics, secondary_metrics (incl. conservation_check)}
    get_vehicles,       # get_vehicles(run_id) -> per-vehicle records (with state_trace)
    get_timeline,       # get_timeline(run_id) -> [{tick, occupancy_by_lot, queue_by_gate, road_load_by_road, overflow_by_lot}] per minute
    register_strategy,  # register_strategy(name, factory)
    export_geojson,     # export_geojson("vitap") -> GeoJSON FeatureCollection
)
```

**Run artifacts** at: `runs/{scenario_id}/{strategy}/seed_{n}/`
- `vehicles.parquet` — per-vehicle records
- `metrics.json` — summary metrics
- `manifest.json` — config hash, seed, git commit, timestamps

---

## How these contracts are enforced

`tests/test_output_contracts.py` checks every column list, key set and shape above from the producer
side (dataset columns, timestep CSV columns, run artifacts, snapshot keys, a snapshot-vs-timeline
consistency check, fork independence, strategy plug-in, the spec entry point). Changing any frozen
shape fails that file, so the change has to be deliberate and communicated.

**Not verifiable from this repo:** that Members 2/3/4's own code consumes these outputs. No teammate
code lives here; the tests above are the stand-in. Confirm with them against these exact shapes.
