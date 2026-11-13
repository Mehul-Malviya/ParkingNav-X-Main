# ParkingNav-X — Objective-to-Implementation-to-Evidence Matrix

**Status:** Academic prototype — all validation is on synthetic data unless stated otherwise.  
**Last updated:** 2026-10-27

---

## How to read this matrix

Each row maps one research or engineering objective to:
- **Implementation** — the module, file, or function that delivers it
- **Evidence** — test, experiment result, or generated artifact that confirms it works
- **Limitation** — honest constraint on the evidence

---

## Research Question

> *Can an event-aware predictive Digital Twin with multi-objective optimization proactively reduce parking search time, waiting time, gate queues, overflow, and unnecessary internal travel compared with conventional allocation strategies?*

---

## 1. Campus Digital Twin

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Model campus (gates, lots, roads, destinations) | `configs/campus/vitap.yaml` + `digital_twin/config_loader.py` | `tests/test_part1_campus_config.py` — 26 tests pass | All capacities/rates are estimated, not measured |
| Validate graph connectivity | `digital_twin/config_loader.py::_validate_graph()` | `test_part2_campus_graph.py` | Based on configured YAML, not surveyed GPS |
| State management (snapshot, restore, fork) | `digital_twin/simulation/state_snapshot.py`, `twin_service.py` | `test_part3_twin_properties.py` | State stored in-memory SQLite; not persistent across restarts |
| Multi-campus generalization | `configs/campus/sample.yaml`, `toy_small.yaml`, `vitap.yaml` | Both load through identical code paths | Toy configs are minimal; no large campus tested |

---

## 2. Simulation Engine

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Vehicle lifecycle (arrive → gate → route → park → depart) | `digital_twin/simulation/engine.py` | `test_part4_part5_simulation.py`, `test_part4_queues.py` | Discrete-time (1-min tick); not continuous-time |
| Occupancy never negative or over capacity | `engine.py` lines 704–708 (invariant asserts) | `test_failure_cases.py::test_no_negative_metrics` | Asserts fire during development; disabled in production mode |
| Deterministic given same seed | `engine.py` RNG discipline | `test_part4_part5_simulation.py::test_same_seed_produces_byte_identical_metrics` | Windows thread timing may cause ±1ms differences in wall time |
| BPR travel time | `engine.py::bpr_travel_time()` | `test_part7_metrics.py` | BPR calibration constants are assumed, not measured |
| Gate queue model | `simulation/gate_simpy.py` (SimPy) | `test_simpy_gates.py` | M/M/c assumption; arrivals are batch, not Poisson |
| Event-aware demand (1.8× multiplier) | `engine.py::_generate_arrivals()` | `test_part3_event_demand.py::test_event_multiplier_raises_arrivals` | Multipliers are configurable assumptions |

---

## 3. Prediction Engine

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Baseline: HistoricalAverage | `prediction/engine.py::HistoricalAveragePredictor` | MAE=0.049, R²=0.925 (academic-main, 15-min) | Trained on synthetic data; model may have learned simulator assumptions |
| Baseline: MovingAverage | `prediction/engine.py::MovingAveragePredictor` | MAE=0.170, R²=-0.011 — weaker baseline, as expected | Same synthetic data limitation |
| XGBoost with event features | `prediction/engine.py::XGBoostPredictor` | MAE=0.050, R²=0.919, Coverage=86.6% | Coverage < 90% target; small calibration set |
| Conformal prediction intervals | `prediction/engine.py::_calibrate_conformal()` | `test_prediction.py::test_conformal_coverage` | 86.6% empirical coverage vs 90% target |
| No data leakage | Chronological splits in `prediction/evaluate.py` | `test_prediction.py::test_no_data_leakage` | Splits are on synthetic data; real-data splits not yet evaluated |
| Prediction metrics from held-out data | `digital_twin/prediction/evaluate.py::run_evaluation()` | `experiments/results/prediction_metrics.json` | All held-out data is synthetic |

---

## 4. Risk Engine

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Overflow risk (fill > 90%) | `risk/engine.py::overflow_risk()` | `tests/test_risk.py` | Uses DB fill data; defaults to 40% if no live data |
| Gate queue risk | `risk/engine.py::gate_queue_risk()` — queries `gate_state` table | `test_risk.py` | Queue data available only after simulation runs |
| Road congestion risk | `risk/engine.py::road_congestion_risk()` — queries `road_state` table | Functional; returns 0.0 before first simulation run | Road capacity values are estimated |
| Hysteresis (prevent alert flapping) | `risk/engine.py::_apply_hysteresis()` — ON=0.50, OFF=0.40 | `test_risk.py::test_hysteresis_prevents_flapping` | Threshold values are heuristic |
| Proactive trigger | Fires when forecast > 90% AND current < 90% | `optimization/engine.py::_check_proactive_trigger()` | Definition of "proactive" in spec is illustrative |

---

## 5. Optimization Engine

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| J cost function | `J = w1·Waiting + w2·Queue + w3·SearchTravel + w4·UtilizationImbalance + w5·Overflow` | `optimization/engine.py::compute_cost()` | Weights are configurable starting points; not calibrated on real data |
| Weight profiles P1/P2/P3 | `optimization/engine.py::WEIGHT_PROFILES`, `demo_strategies.py::_J_WEIGHT_PROFILES` | `test_optimization.py` | Profile names (P1=min-wait, P2=balanced, P3=max-util) follow spec convention |
| B1 First Available | `simulation/strategy.py::FirstAvailableStrategy` | `experiments/results/results_summary.json` — B1 baseline results | |
| B2 Nearest Available | `simulation/strategy.py::NearestAvailableStrategy` | Same | |
| B3 Prediction Only | `simulation/demo_strategies.py::PredictionOnlyStrategy` | Same | |
| P ParkingNavX Full | `simulation/demo_strategies.py::ParkingNavXFullStrategy` | Same | |
| Hard constraints (no closed lot/gate) | `simulation/engine.py` — strategy receives only open lots/gates | `test_failure_cases.py::test_closed_lot_not_assigned` | |
| Feasible fallback | B2 fallback when P fails; explicit overflow when all full | `test_failure_cases.py::test_all_lots_full` | |

---

## 6. Explainability

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Recommendation explanation | `api/app.py::_explain()` and `_explain_structured()` | `/find_parking` response includes `explanation` object | Explanation is template-based, not derived from SHAP/LIME |
| Cost-component breakdown in response | `api/app.py` — `cost_breakdown` field in each option | `/find_parking` JSON response | Components use heuristic weights, not learned |
| Objective score exposed | `optimization/engine.py` — `objective_score` field | `/recommendations` response | Score is a combined heuristic, not ground-truth cost |
| Operator override | `api/app.py::POST /operator/override` | Code present; not tested with frontend | Override does not bypass hard feasibility constraints |

---

## 7. Experiments

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| E1 Normal day | `configs/scenarios/vitap/E1_normal_day.yaml` | 20 seeds (5 in current summary) | **CRITICAL: need 30 seeds for valid 95% CI** |
| E2 High-demand event | `E2_event_placement.yaml` | 20 seeds | Same |
| E3 Lot closure | `E3_lot_closure.yaml` | 20 seeds | Same |
| E4 Gate closure | `E4_gate_closure.yaml` | 20 seeds | Same |
| E5 Noise robustness (σ=0/10/20%) | `E5_noise_{0,10,20}.yaml` | 5–8 seeds | Insufficient for CI; pilot only |
| E6 Ablation study | `E6_ablation_{A-D}.yaml` | 5–8 seeds | Pilot only |
| E7 Real-observation replay | `E7_replay.yaml` + `data/observations/vitap_observations.csv` | Framework present; observations are synthetic | **No real campus observations collected** |
| Paired statistical comparison | Common seeds across B1/B2/B3/P | `scripts/run_all_experiments.py` | Paired t-test not yet reported; need 30 seeds |
| Result charts | `scripts/generate_charts.py` | `experiments/results/charts/` (12 PNGs) | Generated from 5-seed run; regenerate after 30-seed run |

---

## 8. API

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| All required endpoints | `digital_twin/api/app.py` — 20+ routes | `tests/test_api.py`, `test_output_contracts.py` | |
| Startup pre-warm | `@app.on_event("startup")` calls `get_predictor()` | API starts without cold-start delay | |
| `/health` endpoint | `GET /health` → `{"status":"ok","db":bool,"version":"2.0.0"}` | `test_output_contracts.py` | |
| OpenAPI documentation | FastAPI auto-generates at `/docs` | Run `uvicorn digital_twin.api.app:app` and visit `/docs` | |

---

## 9. Dashboard

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Campus map | `frontend/src/components/CampusMap.jsx` | Code present; uses Leaflet | **Not live-verified in this session** |
| Forecast panel | `frontend/src/components/ForecastPanel.jsx` | Code wired to `GET /predict/all` | Same |
| Scenario controls | `frontend/src/components/ScenarioControls.jsx` | Wired to `POST /simulate` | Same |
| Recommendation panel | `frontend/src/components/RecommendationPanel.jsx` | Wired to `GET /recommendations` | Same |
| Experiment dashboard | `frontend/src/components/ExperimentsDashboard.jsx` | Wired to `GET /experiments/results` | Same |
| No hardcoded mock data | `frontend/src/api.js` — all calls to real backend | Code review confirms no mock constants | Not runtime-verified |

---

## 10. Validation

| Objective | Implementation | Evidence | Limitation |
|---|---|---|---|
| Sim vs observations RMSE/MAE | `scripts/validate_sim_vs_observations.py` | Script runs; produces table | Observations are synthetic (source=synthetic in CSV) |
| Counterfactual label | `digital_twin/validation/calibration.py::honest_counterfactual_label()` | Returns required disclaimer string | |
| Data clearly labelled synthetic | `data/observations/vitap_observations.csv` — every row has `source=synthetic` | Code inspection | **No real campus observations** |

---

## Known Limitations Summary

| ID | Limitation | Impact |
|---|---|---|
| L1 | All data is synthetic | Validation results are self-consistency checks, not real-world evidence |
| L2 | Only 5–20 seeds per experiment cell (target 30) | 95% CIs are too wide to support strong statistical claims |
| L3 | XGBoost conformal coverage = 86.6% (target 90%) | Prediction intervals are slightly under-calibrated |
| L4 | Road congestion risk returns 0 before first simulation run | Risk dimension is uninformative in cold-start state |
| L5 | Frontend not runtime-verified in this session | Live demo correctness unconfirmed |
| L6 | No real VIT-AP campus observations collected | Cannot claim real-world effectiveness |
| L7 | No paired t-test / Wilcoxon results reported | Statistical significance of P vs B1/B2 not formally established |

---

*This matrix is generated from the actual implementation. Every claim should be verifiable by running the referenced test, script, or command.*
