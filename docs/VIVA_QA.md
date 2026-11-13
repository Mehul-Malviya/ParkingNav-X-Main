# ParkingNav-X — Viva Question Preparation

**Grounded in the actual implementation as of 2026-10-26.**  
All answers refer to code that exists and runs; no fabricated results.

---

## Q1. What is your research question?

> Can an event-aware predictive Digital Twin with multi-objective optimization proactively reduce parking search time, waiting time, gate queues, overflow, and unnecessary internal travel compared with conventional allocation strategies?

The system is designed to answer this through controlled simulation: running B1 (First Available), B2 (Nearest Available), B3 (Prediction Only), and P (ParkingNav-X full strategy) on identical demand scenarios and comparing the five outcome metrics.

---

## Q2. What is a Digital Twin in your system?

A Digital Twin is a stateful software model that mirrors the physical campus. In ParkingNav-X:
- **State** includes: lot occupancy, gate queue lengths, road availability, active events, vehicle positions.
- **Behaviour** includes: state transitions (vehicle arrives → queues → parks → departs), occupancy updates, and event-driven demand changes.
- **Prediction layer**: the twin runs 15-minute look-ahead forecasts to make proactive decisions before thresholds are breached.

The twin is implemented in `digital_twin/simulation/state_manager.py` and `digital_twin/twin_service.py`. It is not just a map — it tracks time-varying state and can take snapshots for replay.

---

## Q3. Why XGBoost for prediction?

XGBoost was chosen because:
1. It handles non-linear relationships between time-of-day, day-of-week, and occupancy without manual feature engineering.
2. It outperformed MovingAverage on all 5 lots in evaluation (MovingAverage R² ≈ −0.01 to −0.18; XGBoost R² = 0.37–0.92).
3. It is compatible with split conformal prediction for uncertainty intervals without distributional assumptions.
4. HistoricalAverage also performed well (comparable to XGBoost on synthetic data), which is expected because the synthetic demand model is periodic.

Evaluation metrics computed: MAE, RMSE, MAPE, **WAPE** (Weighted Absolute Percentage Error = Σ|error| / Σ|actual| × 100), R², and 90% conformal coverage. WAPE is the primary metric cited in the spec because it is less sensitive than MAPE to near-zero targets.

**Caveat:** On real data with more noise and irregular events, the gap between XGBoost and simple baselines would likely be larger.

---

## Q4. What makes a recommendation "proactive"?

A recommendation is proactive when:
- The 15-minute forecast for a lot exceeds 90% fill rate **AND**
- The current fill rate is below 90% (not yet critical).

This means the system acts before the problem occurs. The trigger is in `optimization/engine.py::_check_proactive_trigger()`. A hysteresis band (same threshold for both current and forecast) prevents oscillating recommendations.

**Illustrative example:** Lot at 72% now, forecast 94% in 15 minutes → system recommends rerouting before drivers arrive to find it full.

---

## Q5. How does the ablation study work?

The E6 ablation evaluates each component's contribution by removing it:

| Variant | Flags off | Expected effect |
|---------|-----------|-----------------|
| E6-A | optimization, uncertainty, proactive | Uses only forecasts for lot selection |
| E6-B | uncertainty, proactive | Adds gate load balancing |
| E6-C | proactive | Adds uncertainty-aware lot penalisation |
| E6-D (full P) | none | All components active |

Each variant runs with the same seeds as E1 so demand is paired. A monotonic improvement A→B→C→D would confirm each component adds value. Results are stored in `experiments/results/all_results.json`.

---

## Q6. What are the limitations of using synthetic data?

1. **Circularity:** The prediction model learns the patterns from the same demand model that drives the simulation. High R² may reflect learned simulator assumptions, not real-world generalisability.
2. **Optimistic baselines:** If the real demand is noisier or has irregular events, all strategies (including baselines) will perform worse than on clean synthetic data.
3. **No validation against real campus:** We cannot claim the strategies produce the predicted improvements in practice.

Honest label: *"Simulation-based estimate; not a deployed real-world intervention."*

---

## Q7. What feasibility constraints does the optimizer enforce?

Hard constraints (checked before any assignment):
- Closed lots are never assigned (lot status = CLOSED in DB).
- Closed gates are never routed through.
- Lot occupancy never exceeds capacity (invariant enforced in `engine.py`).
- Occupancy never goes negative.
- Routes must exist in the campus graph (NetworkX shortest path; raises if disconnected).

Accessible spaces are reserved per lot (configurable `reserved_accessible_spaces` in `vitap.yaml`).

---

## Q8. How do conformal prediction intervals work in your system?

Split conformal prediction:
1. Train XGBoost on the training split.
2. Compute residuals (|predicted − actual|) on a held-out calibration split (15% of data).
3. Take the 90th percentile of calibration residuals as the interval half-width.
4. At inference: `[prediction − width, prediction + width]` gives a 90% coverage interval.

Coverage on the test set ranges from 86.6% to 92.1% across lots (target is 90%), confirming the method is approximately valid. See `digital_twin/prediction/engine.py::XGBoostPredictor`.

---

## Q9. What do B1, B2, B3, and P mean?

| Code | Name | Decision logic |
|------|------|---------------|
| B1 | First Available | Assign the first lot in a fixed priority order with space remaining |
| B2 | Nearest Available | Assign the closest lot (by configured travel cost) with space remaining |
| B3 | Prediction Only | Avoid lots forecast above 85% fill; otherwise nearest available |
| P | ParkingNav-X | Full: proactive trigger + forecast + uncertainty penalisation + gate load balancing + multi-objective J |

B1 and B2 are conventional strategies that do not use prediction. B3 adds prediction. P adds all remaining components on top of B3.

---

## Q10. What is the objective function J?

`J = w1·WaitingTime + w2·QueueCost + w3·SearchTravel + w4·UtilizationImbalance + w5·OverflowPenalty`

Each component is normalised to [0,1]. Weights sum to 1.0. Three pre-configured weight profiles:
- P1 (default): prioritises waiting time (w1=0.4)
- P2: equal weights (0.2 each)
- P3: prioritises overflow prevention (w5=0.5)

The optimizer selects the lot with the lowest predicted J score after applying feasibility constraints.

---

## Q11. How do you ensure reproducibility?

1. Each simulation run uses an explicit `random_seed` set in `ScenarioConfig`.
2. The same seed, scenario, and strategy always produce identical `total_ever_parked`, `avg_search_time_min`, etc.
3. Each run manifest records: git commit hash, scenario YAML, seed, strategy, timestamps.
4. Results are stored as parquet files in `runs/` and JSON in `experiments/results/`.
5. The batch runner skips already-completed run IDs to avoid overwriting valid results.

---

## Q12. Why does the overflow lot have R² = 0.37?

The overflow lot has very low and flat occupancy in the synthetic data (rarely used except in high-demand scenarios). R² measures what fraction of variance the model explains — if variance is tiny (all values near zero), even small absolute errors produce low R². The absolute MAE is 0.041 (fill rate, out of 1.0), which is comparable to other lots. R² is a poor discriminator for near-constant targets.

---

## Q13. How does the risk engine use prediction uncertainty?

The risk engine (`digital_twin/risk/engine.py`) computes overflow risk using:
- Current fill rate from `lot_occupancy_history` DB table
- Forecast fill rate from the predictor's `get_forecast_snapshot()`
- Upper confidence bound (90th percentile) when available

Risk score uses a sigmoid formula: `risk = 1 / (1 + exp(-steepness * (fill - threshold)))`. When uncertainty is provided, the upper bound is used instead of the point forecast, making the risk assessment conservative (safety-biased).

---

## Q14. What happens when prediction fails?

The system has explicit fallback behaviour:
- If XGBoost prediction raises an exception, `get_predictor()` falls back to `MovingAverage`.
- If `MovingAverage` also fails (e.g., no history), the predictor returns the last known fill rate.
- The API response includes a `fallback_used: true` flag when a fallback is active.
- The risk engine falls back to a 40% fill assumption if the DB has no history.
- The optimizer still returns a recommendation in all cases; it may be less optimal.

---

## Q15. How is the campus graph constructed?

The campus graph is a weighted directed graph (NetworkX `DiGraph`) loaded from `configs/campus/vitap.yaml`. Nodes are gates, lots, intersections, and destinations. Edges carry travel cost (estimated seconds) computed from BPR formula using configured road length, lane count, and free-flow speed. Graph connectivity is validated at load time — unreachable nodes raise a configuration error.

---

## Q16. What is the B4 / P naming issue?

Early code used `"B4"` as the internal key for `ParkingNavXFullStrategy`. The capstone spec uses `"P"`. The `"B4"` alias has been fully removed from all code paths: `app.py`, `optimization/engine.py`, `run_batch.py`, and `run_all_experiments.py` all use `"P"`. Historical results in `all_results.json` that were recorded under the `"B4"` label have been relabelled to `"P"` in-place, so aggregated summaries and the comparison table are clean.

---

## Q17. Why does MovingAverage perform poorly (R² < 0)?

MovingAverage uses a trailing window of recent values. It performs well for stationary series but fails to capture daily/weekly periodicity — it always lags behind morning peaks and afternoon drops. R² below 0 means the model does worse than simply predicting the mean. This validates the choice of a periodic model (HistoricalAverage or XGBoost with time features).

---

## Q18. What is the `total_ever_parked` metric?

`parked_vehicles` is a snapshot at simulation end (vehicles still occupying a space). Most vehicles park and then depart during the simulation window, so the snapshot looks low. `total_ever_parked` is the cumulative count of all vehicles that successfully parked at any point during the run. In E1/B1/seed_0: total_ever_parked = 399/400 vehicles (99.75% success rate). This is the correct metric for evaluating strategy effectiveness.

---

## Q19. What are the three campus configurations?

| Config | Purpose | File |
|--------|---------|------|
| vitap | Real VIT-AP layout (5 lots, 2 gates, 17 destinations) | `configs/campus/vitap.yaml` |
| toy_small | Minimal demo (3 lots, 1 gate) | `configs/campus/toy_small.yaml` |
| sample | Mid-size synthetic campus | `configs/campus/sample.yaml` |

All three load through the same code paths (`config_loader.py`, `SimulationEngine`), demonstrating configuration-driven generalization. No code changes are required to switch campuses.

---

## Q20. What is the honest assessment of the system's current state?

**What works:**
- Backend (FastAPI) starts cleanly; all 16+ endpoints respond correctly.
- Simulation engine enforces all invariants; 307/321 tests pass.
- XGBoost prediction is live with conformal intervals; metrics from held-out data.
- Risk engine feeds from real simulation output.
- Ablation (E6) and noise (E5) experiments are wired and produce differentiated results.
- `/experiments` API endpoints connect the frontend's Experiments tab.

**What is incomplete:**
- The full E1–E6 experiment matrix (30 seeds × 4 strategies) has not yet been run since Phase 3 fixes. Strategy comparison results are not yet available.
- Frontend has not been verified against the live backend (unit tests pass; end-to-end browser test not performed).
- No real VIT-AP campus data has been collected or used.
- `docs/RESULTS_SUMMARY.md` Section 2 will be empty until the experiment matrix runs.

**What we would not claim:**
- That ParkingNav-X is proven to reduce parking search time by any specific percentage at VIT-AP.
- That the model generalises to real-world demand without validation on real data.
- That the system is ready for operational deployment.

---

## Objective-to-Implementation-to-Evidence Matrix

| System Objective | Implementing Module | Key Code Location | Evidence |
|-----------------|--------------------|--------------------|----------|
| Reduce parking search time | `ParkingNavXFullStrategy` (P) | `simulation/demo_strategies.py::assign()` | E1–E4 experiments: `avg_search_time_min` in `all_results.json` |
| Reduce gate waiting/queue | Gate queue penalty in P strategy | `demo_strategies.py` `GATE_QUEUE_WEIGHT=50.0` | `avg_gate_queue`, `max_gate_queue` in experiment metrics |
| Predict lot occupancy (15 min) | `XGBoostPredictor` + conformal intervals | `prediction/engine.py::predict()` | MAE, RMSE, WAPE, R², coverage in `prediction_metrics.json` |
| Proactive rerouting before overflow | Forecast-trigger in optimizer | `optimization/engine.py::_check_proactive_trigger()` | PROACTIVE_REROUTE alerts in `/recommendations` response |
| Multi-objective cost minimisation | `MultiObjectiveOptimizer` | `optimization/engine.py::compute_cost()` | `cost_J` field in experiment results; `/optimize` API |
| Event-aware demand modelling | Scenario event injection | `simulation/engine.py`, `ScenarioConfig.events` | E2 (event placement) vs E1 (normal): demand spike visible in lot fill history |
| Uncertainty-aware assignment | Conformal upper bound in P | `demo_strategies.py` `use_uncertainty` flag | E6-C vs E6-D ablation: overflow events differ |
| Configurable campus topology | YAML-driven campus graph | `config_loader.py`, `configs/campus/vitap.yaml` | `test_config_validation.py` (54 tests pass) |
| Reproducible experiments | Seeded RNG + run manifests | `simulation/engine.py::run()` seed parameter | Same seed → identical metrics (verified in `test_simulation.py`) |
| Overflow prevention | Hard fill threshold (0.95) + J penalty | `demo_strategies.py`, `optimization/engine.py::overflow_penalty()` | `overflow_events_count` in experiment results |
| Risk scoring and alerting | `RiskEngine` | `risk/engine.py::compute_all()` | `/risk/current` and `/risk/forecast` API responses; `test_risk.py` |
| Ablation study (component contribution) | `ablation_flags` in `ScenarioConfig` | `simulation/engine.py` + `demo_strategies.py::update_policy()` | E6-A/B/C/D results in `all_results.json` |
| Noise robustness | `ForecastNoiseInjector` | `simulation/engine.py::ForecastNoiseInjector.perturb()` | E5 noise experiments (levels 0, 10, 20) |
