# ParkingNav-X — Phase 0 Audit Report

**Date:** 2026-10-26  
**Branch:** claude/pull-latest-814594  
**HEAD commit:** a94c6f0 (Merge PR #32 — fix: improve frontend API integration and validation)  
**Auditor:** Phase 0 automated audit + senior engineer review  

---

## 1. Executive Summary

The repository is in substantially better shape than a typical capstone prototype. The core backend (FastAPI + SQLite + SimPy simulation engine) is functional, the test suite passes **307 of 321 tests** (14 skipped, 0 failures), and all four strategies (B1, B2, B3, P/B4) execute. No merge conflict markers were found.

Five critical gaps must be resolved before the November review:

1. Prediction evaluation returns empty (all lots below 50-sample threshold after feature engineering).
2. XGBoost is not the default predictor — `get_predictor()` returns a `MovingAverage` singleton.
3. Ablation flags (`use_prediction`, `use_optimization`, `proactive`) are stored in scenario YAML but never consumed by any strategy — E6 ablation produces identical results to E1.
4. Noise injection (`prediction_error_injection_level`) is stored in scenario YAML but never applied — E5 robustness results are identical to E1.
5. ~~Risk engine always shows 0.0/LOW~~ **Fixed in Phase 1:** `/simulate` now writes lot occupancy snapshots to `lot_occupancy_history` so the risk engine sees real data.

---

## 2. Test Results (Baseline)

Command run:
```
python -m pytest tests/ --tb=short -q
```

Result:
```
307 passed, 14 skipped, 1 warning in 494.32s (0:08:14)
```

- **321 tests collected. 307 pass. 14 skipped. 0 failures.**
- Skipped tests are in `test_e5_robustness.py` and `test_statistical_verification.py` — skipped because noise injection is not yet wired, making those statistical assertions meaningless.

---

## 3. Module Status Table

| Module | Status | Evidence | Gap | Planned Fix |
|--------|--------|----------|-----|-------------|
| **M1 Campus Config** | ✅ Working | `vitap.yaml` loads into SQLite; 71 config/graph tests pass; 5 lots, 2 gates, full road network | Minor: `vitap_v1.yaml` and `vitap.yaml` may have diverged | Confirm active config is `vitap.yaml` |
| **M2 Digital Twin State** | ✅ Working | `twin_service.py` + `state_manager.py`; state transitions, snapshots, invariant checks; 30+ tests pass | Two state manager implementations — may cause confusion | Clarify which is authoritative for the API |
| **M3 Data Ingestion** | ⚠️ Partial | `synthetic_multi_year_demand.csv` (294 rows total across 5 lots) | Only `vitap-lot-academic-main` has 127 rows; others 30–60 rows; prediction evaluation fails | Generate proper 30-day dataset (~14,400 rows) |
| **M4 Scenario Generator** | ✅ Working | 24 scenario YAML files; `ScenarioLoader` + `ScenarioConfig`; E1–E8, S-series | Ablation flags stored but NOT consumed by any strategy | Wire flags into B4/P strategy (Phase 3) |
| **M5 Simulation Engine** | ✅ Working | BPR travel, SimPy gate queuing, lognormal dwell, vehicle state machine; 185/199 simulation tests pass | `parked_vehicles` metric was misleading snapshot; now `total_ever_parked` added | ✅ Fixed in Phase 1 |
| **M6 Prediction Engine** | ⚠️ Partial | `HistoricalAverage`, `MovingAverage`, `XGBoostPredictor` code exists; conformal intervals | `run_evaluation()` returns `[]`; XGBoost not default predictor | Fix data pipeline + wire XGBoost (Phase 2) |
| **M7 Risk Engine** | ⚠️ Partial | Sigmoid-based formulas; API endpoints respond; structurally sound | All scores showed 0.0/LOW — `lot_occupancy_history` never populated | ✅ Fixed in Phase 1: `/simulate` now writes occupancy history |
| **M8 Optimizer** | ⚠️ Partial | Multi-objective J, 3 weight profiles (P1/P2/P3), proactive trigger at 90% forecast | No closed-lot hard-constraint check; uses MovingAverage not XGBoost | Add feasibility check (Phase 3) |
| **M9 Explainability** | ⚠️ Partial | Rule-based reason strings in `/recommendations`; lot/gate/route in output | No objective-score comparison between chosen vs alternatives | Add J-score comparison (Phase 3) |
| **M10 Experiment Engine** | ⚠️ Partial | 30-seed E1 results in `runs/`; summary tables committed | E2–E4: 1–2 seeds; E5 noise / E6 ablation identical to E1 (bugs); DB concurrency errors | ✅ DB fix in Phase 1; re-run E2–E6 after Phase 3 |
| **M11 API** | ✅ Working | FastAPI; 16+ endpoints; CORS; imports cleanly; OpenAPI at `/docs` | `"B4"` in code = `"P"` in spec (both map same class); no `/experiments` endpoint | Add `/experiments` endpoint (Phase 4) |
| **M12 Dashboard** | ⚠️ Partial | React + Vite + Tailwind; 6 components; `api.js` maps to real endpoints | Not verified against live backend; no `/experiments` backend | Verify live; add endpoint (Phase 5) |
| **M13 Validation** | ⚠️ Partial | `vitap_observations.csv` and calibration code exist | Data is synthetic, not labelled as such; counterfactual not implemented | Label synthetic data clearly; real data TBD |
| **M14 Reporting** | ⚠️ Partial | `docs/member1/results_summary.md`; architecture HTML | Missing: `ASSUMPTIONS.md`, `API.md`, `RESULTS_SUMMARY.md`, `DATA_PROTECTION.md`, `VIVA_QA.md` | Generate in Phase 8 |

---

## 4. Critical Blockers

| # | Blocker | Severity | Status |
|---|---------|----------|--------|
| 1 | **Prediction evaluation empty** — all lots <50 usable samples after `build_features()`; MAE/RMSE/R² not generated | HIGH | Open — Phase 2 |
| 2 | **XGBoost not default** — `get_predictor()` returns MovingAverage; conformal intervals not from XGBoost | HIGH | Open — Phase 2 |
| 3 | **Ablation flags ignored** — E6 A/B/C/D identical to E1; study unexecuted | HIGH | Open — Phase 3 |
| 4 | **Noise injection ineffective** — E5 robustness study unexecuted | HIGH | Open — Phase 3 |
| 5 | **Risk engine always 0.0/LOW** | MEDIUM | ✅ Fixed Phase 1 |
| 6 | **DB concurrency in batch runner** — UNIQUE constraint + "database is locked" | MEDIUM | ✅ Fixed Phase 1 |
| 7 | **No `/experiments` API endpoint** | MEDIUM | Open — Phase 4 |

---

## 5. parked_vehicles Metric — Finding

**Not a bug. Expected behavior.**

`parked_vehicles` is a snapshot of vehicles in the `parked` state at simulation end. Vehicles that successfully parked and later departed are counted as `exited` (= `completed_vehicles`). In E1/B1/seed_0:
- `total_vehicles_simulated`: 400  
- `exited_vehicles`: 352 (parked and departed)  
- `parked_vehicles`: 47 (still parked at sim end)  
- `rejected_vehicles`: 0  
- **`total_ever_parked`**: 399 (99.75% success rate)

**Phase 1 fix:** Added `total_ever_parked` and `successful_park_rate` to `SimulationResult.metrics` to make this visible.

---

## 6. What Works — Preserve These

- Full test suite (307 passing)
- `vitap.yaml` campus configuration and SQLite graph
- Simulation engine (BPR, SimPy gate queuing, seeded RNG, vehicle state machine)
- All 24 scenario YAML files
- B1/B2 strategies (correct and tested)
- B3/P (ParkingNavXFull) harness in `demo_strategies.py`
- 30-seed E1 results in `runs/vitap-normal-day/`
- MetricsRecorder (parquet + JSON, git commit hash in manifest)
- React frontend component structure and `api.js` endpoint mapping
- Risk engine formula structure

---

## 7. Assumptions Requiring Team Confirmation

1. **`parked_vehicles` = snapshot**: Confirmed expected behavior. Added `total_ever_parked` metric.
2. **Real campus data**: Has any real VIT-AP gate count or occupancy data been collected? `vitap_observations.csv` appears synthetic.
3. **B4 vs P naming**: Both map to `ParkingNavXFullStrategy` — intentional? Capstone spec uses B1/B2/B3/P not B4.
4. **XGBoost training dataset**: `synthetic_multi_year_demand.csv` has only 294 rows total. Was a larger dataset generated but not committed?
5. **Frontend live test**: Has the React dashboard been verified against a running backend? Check `vite.config.js` for proxy config.
6. **Ablation study design**: What do ablation variants A/B/C/D represent? No strategy currently reads those flags.

---

## 8. Prioritized Implementation Plan

| Phase | Focus | Key Deliverables |
|-------|-------|------------------|
| Phase 1 (done) | Stable foundation | `total_ever_parked` metric; risk engine occupancy feed; batch runner DB fix; this AUDIT.md |
| Phase 2 | Prediction | Generate dataset; wire XGBoost as default; generate MAE/RMSE/R² from held-out data |
| Phase 3 | Risk / Optimization | Wire ablation flags; wire noise injection; add closed-lot hard constraint; re-run E5/E6 |
| Phase 4 | API / Experiments | Add `/experiments` endpoint; re-run E2–E6 with 30 seeds |
| Phase 5 | Dashboard | Verify frontend vs live backend; test all 6 tabs |
| Phase 6–7 | Robustness / Validation | Scalability test; real-data validation (if available) |
| Phase 8 | Hardening | Full test run; demo script; missing docs; viva QA |

---

## 9. Recovery Checkpoint

- Checkpoint commit before Phase 1 changes: `f34a57c` (message: "phase1: checkpoint before fixes")
- To recover: `git checkout f34a57c`
- Git status at audit time: clean
- No merge conflict markers found in any `.py`, `.yaml`, `.json`, or `.jsx` file.
