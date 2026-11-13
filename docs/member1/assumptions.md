# Assumptions — Member 1

**Owner:** Jyothi Reddy Pula (23BCE7882) · VIT-AP · ParkingNav-X

All numbers that are not directly measured are listed here with their source and impact.

---

| # | Assumption | Value | Source | Impact if Wrong | How Tested |
|---|-----------|-------|--------|----------------|------------|
| 1 | Gate service rate | 6 veh/min/lane | Estimated (observed gate ~10 sec/vehicle) | Queue length over/under estimated | Calibration vs real gate counts |
| 2 | Dwell time distribution | Lognormal, median 120 min | Estimated from class schedule (90-min slots) | Lot occupancy curve shape changes | Dwell distribution test |
| 3 | Driver compliance rate | 0.85 | Literature (0.70–0.92 range for guidance systems) | Overflow events change ±10% | E6 ablation |
| 4 | BPR parameters (0.15, β=4) | Standard values | Bureau of Public Roads standard | Travel time estimates off | Unit test at flow=0 and flow=capacity |
| 5 | Lot capacities (VIT-AP) | See vitap.yaml | Estimated from satellite imagery + campus map | Overflow timing shifts | Real observation calibration |
| 6 | Road free speeds | 20 km/h internal | Estimated (campus speed limit) | Travel times off ±15% | Calibration |
| 7 | Event demand multiplier (placement) | 1.8× | Assumed; placement drives bring external visitors | E2 results scale with this | Statistical verification test |
| 8 | Arrival profile shape | Piecewise linear, peak 8–10 AM | Observed informally; calibrated later | Arrival timing off | Arrival timing statistical test (multinomial sampling from rate profile) |
| 9 | Reserved spaces (accessible/staff) | See vitap.yaml | Campus policy estimate | Effective capacity slightly off | Config validator |
| 10 | Decision cycle period | 5 min | Design choice (balance responsiveness vs cost) | Faster = more accurate, slower = cheaper | Ablation (proactive flag) |
| 11 | Warm-down period | 30 min | Design choice: no new arrivals in last 30 min so in-transit vehicles reach terminal state | in_system metric inflated without warm-down | Re-measured at 10 s tick with simulated SEARCHING (E2, 30 seeds): in_system 0.25% without warm-down (10 mid-transit + 25 departing) vs 0.17% with it (all 24 departing). Residual are departure-phase vehicles exiting campus |
| 12 | Gate service rate (main) | 6 veh/min (2 lanes × 3 veh/min/lane) | ASSUMED — no physical measurement available; 3 veh/min/lane ≈ 20 s/vehicle is typical for swipe/RFID gates | Gate queue and waiting_time_seconds scale with this; underestimating rate inflates queue length | Gate congestion scenario shows non-zero queue when arrival rate exceeds 6 veh/min |
| 13 | Gate service rate (visitor) | 3 veh/min (1 lane × 3 veh/min/lane) | ASSUMED — same basis as assumption 12; visitor gate is single-lane | Same impact as assumption 12 | Same |
| 14 | Sports lot driveable road | 534 m, 107 s from main gate | Estimated from satellite image (straight-line ~400 m, road factor ×1.33) | Sports lot always at 0% occupancy without this road | Fix 4: added vitap-road-main-gate-to-sports-lot; verified by graph-reachability test |
| 15 | Dwell time cap | [30, 480] min; median ~120 min (Lognormal μ=4.8, σ=0.6) | Code: `DWELL_MINUTES_RANGE=(30,480)`; median from lognormal params | **Limitation:** real event visitors may stay 6–10 h (concerts, sports); the 480-min hard cap means all event vehicles depart by tick 480 even if they arrived at tick 75. This drives the post-event lot recovery visible in E2. If extended dwell were modelled, academic-main would stay full longer and post-event search times would remain elevated. | Checked: no vehicle in 30-seed run has dwell > 480 min |
| 16 | Simulation tick | 10 s (spec default), set per scenario by `time_step_sec` (1–60, must divide 60) | Spec: tick = time_step_sec, default 10 s | Scenario YAML times (arrival profiles, timed closures, warm-down) stay in minutes and are converted by the engine. Logged `tick` fields and the per-minute `timesteps` stay in minutes (Member 2's frozen contract); traces additionally carry `t_sec`. Gate service accumulates `capacity x dt` credit per tick (6 veh/min = 1 vehicle per 10 s tick; 3 veh/min = 1 per 20 s). Sub-minute arrival time is spread evenly across a minute's ticks (no extra RNG draws). BPR flow is counted per simulated minute. | Runs take ~3.5 s (400 veh); `test_part5`-style tests that need every vehicle terminal must treat a departing vehicle as terminal |
| 17 | Parking search time | base 0.5 min + 5.5 min x occ^2, **simulated**: on reaching its lot a vehicle reserves a space, spends exactly that time in SEARCHING, then PARKS and starts its dwell | Spec formula (k chosen so full lot = 6 min) | Dwell starts after the search, so lots fill/empty a few minutes later than when search was only a metric; conservation now separates driving and searching | test_phase7 search-time growth test; `test_output_contracts` (occupancy == vehicles in SEARCHING+PARKED) |
| 18 | Overflow event | Logged only when a vehicle is REJECTED_OVERFLOW | Spec: "no feasible lot -> overflow event++" | Reassignments after a lot fills mid-transit are tracked in reassigned_count, not as overflow | overflow_events_count == rejected on forced-closure run |
| 19 | Dwell time by event / vehicle type | Global lognormal (median ~120 min) unless `vehicle_types` (per-type share, `dwell_median_minutes`, `dwell_sigma`) or `event_conditions.dwell_median_minutes` / `dwell_sigma` are set. Precedence: event window > vehicle type > global | Spec: dwell lognormal by vehicle type / event. **No calibrated values exist**: only E8 sets a mix (students 50% / 240 min, staff 30% / 420 min, visitors 20% / 60 min), and those numbers are ASSUMED placeholders | Event/type dwell shifts post-event lot recovery; E8 results are illustrative, not evidence about VIT-AP | `test_dwell_override.py`, `test_vehicle_types.py` (default unchanged; mix follows shares; dwell differs by type in a run) |
| 20 | Gate server model | Default `gate_model: tick` (capacity x dt credit). Optional `gate_model: simpy`: multi-lane SimPy servers, lanes = round(capacity / 3 veh/min/lane), 60/(rate per lane) s fixed service time (6 veh/min = 2 lanes x 20 s), vehicle admitted when service completes | Spec: optional SimPy for gate servers. Lane count is derived, not configured: gates only store a total `capacity`; the 3 veh/min/lane rate is ASSUMED (see #12-13) | Under SimPy an empty gate still costs one 20 s service; at low load wait ~0.34 min vs ~0 (tick). Under overload both agree (parking_full: 8.83 vs 8.63 min) | `test_simpy_gates.py` (skipped if simpy is not installed) |
| 21 | Simulation entry points | `python -m simulation run --scenario S1 --strategy nearest --seed 7` (spec form) and `python -m digital_twin.simulation.cli run ...` are the same code; aliases S1..S8 = E1, E2, E3, E4, E5_noise_0, E6_ablation, E7_replay, E8_vehicle_types | Spec VERIFY command | none | `test_output_contracts::test_spec_entry_point_python_m_simulation` |

---

---

## `data/synthetic_observations.csv` — Changes Made

| Change | Detail | Why |
|--------|--------|-----|
| Lot ID remap: `vitap-lot-1` → `vitap-lot-academic-main` | Original placeholder IDs did not match vitap.yaml v2 parking_lot_ids | vitap.yaml was updated to descriptive IDs in v2; validate_observations.py checks against vitap.yaml, so old IDs failed validation |
| Lot ID remap: `vitap-lot-2` → `vitap-lot-sports` | Same reason as above | Same |
| Overflow rows capped at `total_capacity` (120) | Four rows in Day 1 had `occupied_spaces` of 122, 130, 127, 123 — exceeding `total_capacity=120` | validator check #4 rejects `occupied_spaces > total_capacity`; the original values were used to represent physical overflow (vehicles parked illegally/on grass); the `notes` column retains the original intent ("At capacity - overflow vehicles redirected") |

**All synthetic data is labelled "SYNTHETIC" in run manifests. Counterfactual results are labelled "simulation-based estimate."**

**`data/synthetic_observations.csv` is synthetic data generated to match realistic VIT-AP campus patterns (dates 15–16 Oct 2026 are future dates at time of writing). A real counting day using 15-minute aggregate gate counts is planned before final submission. Once collected, this file will be replaced and E7 re-run.**
