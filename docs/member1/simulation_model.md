# Simulation Model — Member 1

**Owner:** Jyothi Reddy Pula (23BCE7882) · VIT-AP · ParkingNav-X

---

## Engine Type

Discrete-time engine, 1 tick = `time_step_sec` seconds (default 10 s, per the spec). Same seed → identical output (deterministic). Scenario YAML times (arrival profiles, closures, warm-down) are in minutes; the engine converts them. Logged `tick` fields and the per-minute `timesteps` stay in minutes so downstream consumers (Member 2's 5-minute windows) are unaffected; vehicle traces also carry `t_sec` (seconds). Gate service is `capacity (veh/min) x dt` credit per tick; BPR flow is counted per simulated minute.

---

## Arrival Model — Time-Varying Demand (Multinomial Sampling)

Rate varies with time of day:  
`λ(t)` = piecewise linear curve (morning peak, lunch, evening exit)

Event-aware rate:  
`λ_event(t) = λ(t) × demand_multiplier`  
(only zones affected by the event get extra demand)

**What the code does:** a fixed expected total (`vehicle_count`) is derived from the profile integral (∫λ(t)dt scaled to target demand). Arrival times are then sampled from the time-varying rate profile using weighted multinomial sampling (`rng.choices(ticks, weights=weights, k=vehicle_count)`). The weight for each tick is the interpolated rate at that tick, optionally scaled by the event multiplier. This is equivalent to conditioning on the total and drawing arrival times from the normalized rate curve — it is NOT Lewis–Shedler thinning.

---

## Dwell Time — Lognormal Distribution

How long a vehicle stays parked:  
`dwell ~ Lognormal(μ=4.8, σ=0.6)` → median ≈ 120 min, capped [30, 480] min  
Justified: most vehicles park for one class period (~90–120 min); a few stay all day.

**By vehicle type / event (optional, default off):** a scenario may set `vehicle_types: {type: {share, dwell_median_minutes, dwell_sigma}}`
(each vehicle draws a type by `share`, then its dwell from that type's lognormal) and/or `event_conditions.dwell_median_minutes` /
`dwell_sigma` (vehicles arriving inside the event window). Precedence: event window > vehicle type > global. Only E8 sets a mix, with
**ASSUMED placeholder values** (students 240 min, staff 420 min, visitors 60 min); no calibrated values exist yet.

---

## Gate Queue — Multi-Server FIFO

- Service rate is a gate total in vehicles/min (main 6 = 2 lanes × 3, visitor 3 = 1 lane × 3; ASSUMED, not measured)
- Vehicles queue FIFO; wait time = service_start − arrival_time
- Closed gate → queued and arriving vehicles are diverted to the nearest open gate
- **Default model (`gate_model: tick`):** each tick adds `capacity × dt` service credit; a vehicle is admitted the moment a whole unit of credit is available (no service delay on an empty gate)
- **Optional `gate_model: simpy`:** SimPy multi-lane servers (lanes = round(capacity / 3), fixed 20 s service per vehicle); a vehicle is admitted when its service completes, so an empty gate still costs 20 s. Needs `pip install simpy`; under overload both models give the same wait (parking_full: 8.83 vs 8.63 min)

---

## Road Travel Time — BPR Function

Bureau of Public Roads formula:  
`t = t_free × (1 + 0.15 × (flow / capacity)^4)`

- `t_free` = free-flow travel time (length / free_speed)
- `flow` = current vehicle count on road
- `capacity` = road capacity in vehicles/hr
- At flow = capacity: travel time is 1.15× free-flow
- Parameters 0.15 and 4 are BPR standard values (empirically validated in traffic literature)

Route = shortest path by current travel time via Dijkstra (NetworkX).

---

## Parking Search Time

`search_time = base + k × occupancy²`  (base = 0.5 min, k = 5.5 min → 6.0 min at a full lot)

- `base` = 0.5 min; `k` = 5.5 min (spec formula; bounded, no divergence at occ = 1)
- Grows quadratically as the lot fills. It is simulated: on arrival the vehicle reserves a space (capacity can never be exceeded), spends exactly this time in the SEARCHING state, then PARKS and starts its dwell
- If lot full on arrival → vehicle cruises to the next feasible lot and its `reassigned_count` increments; an overflow event is logged only if the vehicle is rejected (no feasible/reachable lot)

---

## Driver Compliance

`compliance_rate = 0.85` (default)  
15% of drivers ignore the recommendation and go to their nearest preferred lot.  
Models realistic human behaviour without requiring RL or agents.

---

## Warm-Down Period

Every scenario YAML includes `warmdown_minutes: 30`. During the last 30 minutes of simulation time, **no new vehicle arrivals are generated**. Vehicles that have already entered the system complete their dwell and departure normally.

**Why:** Without warm-down, vehicles arriving near the simulation end would still be in mid-transit (route/parking_search state) when the clock stops, inflating the `in_system_vehicles` metric artificially. The warm-down allows all in-transit vehicles to reach a terminal state before metrics are recorded.

**Effect measured (E2, 30 seeds, 10 s tick, simulated SEARCHING state, 14,100 vehicles):** in_system at end-of-sim is 0.25% (35 vehicles) without warm-down and 0.17% (24 vehicles) with the 30-min warm-down. Without warm-down, 10 of the 35 are still driving or searching and 25 are departing; with warm-down none are mid-transit and all 24 are in the *departure* phase — they have parked, finished their dwell and are driving out of campus. These are not stalled vehicles; they are completing the journey, and warm-down only removes the mid-transit ones. (At the earlier 1-minute tick the gap was larger, ~2.45% vs ~1.05%, because each state cost a whole minute.)

---

## Forecast Noise (E5) — Plumbing Ready, Results Pending Member 3

`prediction_error_injection_level` (0.0 / 0.10 / 0.20) is accepted by `ScenarioConfig` and stored in the YAML. The `ForecastNoiseInjector` in `digital_twin/simulation/forecast_noise.py` applies Gaussian noise to forecasts when invoked.

**Current status:** The engine passes `forecast=None` to `strategy.update_policy()`. Neither B1 (FirstAvailableStrategy) nor B2 (NearestAvailableStrategy) reads forecast data. As a result, E5_noise_0, E5_noise_10, and E5_noise_20 produce **identical B1/B2 results** — the noise parameter has no effect on the baselines.

**When E5 becomes meaningful:** once Member 3's optimizer reads `use_prediction` and consumes the noisy forecast, E5 will measure robustness degradation as noise increases. B1/B2 are noise-immune by construction (reactive, no forecast dependency), which is itself a useful baseline for comparison.

**Confirmed:** 30-seed run with seed override shows B1 search = 3.93 min and B2 search = 2.26 min for all three noise levels, bit-for-bit identical.

---

## Gate Model — Service Rate and Queue Analysis

**VITAP gate configuration (assumed — to be measured on counting day):**

| Gate | Lanes | Rate/lane | Total rate |
|------|-------|-----------|------------|
| vitap-gate-main | 2 | 3 veh/min | 6 veh/min |
| vitap-gate-visitor | 1 | 3 veh/min | 3 veh/min |

**Why the gate queue is 0 in E4 (gate-main closed ticks 45–105):**

When gate-main closes, arrivals divert to visitor gate (capacity 3 veh/min).
E4 uses the E1 arrival profile, peak rate ≈ 1.2 veh/min total, ≈ 0.6–1.2 veh/min at visitor gate after diversion. This is well below the 3 veh/min service capacity → queue never builds. This is physically correct; a queue would only form if arrival rate exceeds gate service rate.

**Gate-congestion burst (scenario file since removed):** a burst of 4.0 veh/min (ticks 30–90) split uniformly over both gates (~2 veh/min each) is still below gate capacity, so gate queue stays near 0. A queue forms only when arrival rate exceeds service rate (see test below).

**Queue grows when arrival rate > service rate — test confirmation:** A test (`test_gate_queue_grows_under_overload`) creates a scenario with a single gate of capacity 1 veh/min and arrival rate 6 veh/min and verifies that gate queue depth exceeds 0 within the burst window. The queue logic itself is confirmed correct; VITAP's current gate capacity is simply adequate for the modelled demand.

**When to revisit:** Measure actual gate service time (seconds/vehicle) on the counting day. If real service time > 20 s/vehicle (< 3 veh/min/lane), adjust `capacity` in vitap.yaml and re-run E4.

---

## Scenario Result Notes

**wait and gate-queue are identical for B1 and B2 (all non-stress scenarios):**
Both strategies only choose *which lot* to assign a vehicle. Gate assignment is random (uniform over open gates), independent of strategy. Wait time = time spent in gate queue; gate queue depth = vehicles queued at any gate. Neither metric is affected by lot choice — only gate throughput and arrival rate matter. These can only improve if Member 3's optimizer also controls gate assignment or pre-clears specific gates before peak arrivals.

**parking_full is a stress scenario with a non-standard duration:**
It runs for 90 minutes (vs E1–E5's 600 min), so its raw metric values are not directly comparable. It tests an extreme load condition (600 vehicles > 472 spaces), not typical campus operation. gate_congestion, high_traffic and peak_hour were removed from the repo.

**road_closure — inside-window vs outside-window travel distance (B1/B2, 30 seeds):**

| Strategy | In-window (minutes 60–180) | Out-of-window | Detour |
|----------|--------------------------|---------------|--------|
| B1 | **1267 m** | 978 m | +290 m (+30%) |
| B2 | **685 m** | 596 m | +89 m (+15%) |

The whole-day average (B1: 1062 m, B2: 622 m) understates the closure effect because ~79% of arrivals are unaffected. During the closure, B1 is diverted to admin (520 m) and sports (534 m) — farther than academic (450 m). B2 was already using hostel (380 m) and overflow (280 m via visitor gate) so the detour is smaller.

**E3 B2 vs E1 B2 (search 2.26 vs 2.26 min):**
B2 (NearestAvailable) assigns each vehicle to the nearest open lot relative to its entry gate. From gate-main, the nearest lots by travel time are hostel (76 s) and admin (104 s), not academic-main (90 s). From gate-visitor, nearest are overflow (56 s) and admin (70 s). B2 never primarily uses academic-main, so closing it in E3 has no effect on B2's behaviour or search time.

**E3 B1 < E1 B1 (search 2.83 vs 3.93 min):**
B1 (FirstAvailable) always fills the first lot with remaining capacity, in config order. Academic-main (capacity 108) is normally filled first. When it closes (ticks 60–180), B1 routes vehicles to hostel (162), admin (72), and sports (84) — all initially emptier. Lower occupancy → shorter search time per the formula `search = 0.5 + 5.5 × occ²` min. This exposes a structural weakness of B1: it produces worse search times at high occupancy than at medium occupancy. E3 is not a "better" day for B1; it is a day where the forced redistribution accidentally lowers average occupancy during the closure window.

**Over-capacity demand (high_traffic scenario, since removed):**
Campus usable capacity = 108 + 162 + 72 + 84 + 46 = 472 spaces. With 550 vehicles, demand exceeds capacity, yet rejections stay near 0 because dwell times are stochastic (median 120 min, range 30–480 min): early arrivals depart before later ones need the space. Vehicles that find a lot full are re-routed (`reassigned_count`), not rejected; an overflow event is logged only on rejection. The only scenario that produces real rejections is parking_full (600 vehicles in 90 min, ~21.6 rejections per seed for B1).

**E7_replay results are based on synthetic observations (real data pending):**
The E7 YAML replays 350 vehicles with a morning-peak profile derived from the synthetic_observations.csv file. These will be replaced with real arrival-time observations from the counting day (Member 5). Results: B1 search 2.42 min, B2 search 1.97 min, 0 rejections.

---

## Parameters Summary

| Parameter | Value | Source |
|-----------|-------|--------|
| Service rate (gate) | 3 veh/min/lane | **Assumed** — measure on counting day |
| Main gate lanes | 2 | **Assumed** |
| Visitor gate lanes | 1 | **Assumed** |
| BPR α | 0.15 | Standard BPR |
| BPR β | 4 | Standard BPR |
| Dwell μ (lognormal) | 4.8 | Calibrated from observations |
| Dwell σ (lognormal) | 0.6 | Calibrated from observations |
| Compliance rate | 0.85 | Assumption (literature range 0.7–0.9) |
| Decision cycle | 5 min | Design choice |
| Warm-down | 30 min | Design choice (see section above) |
