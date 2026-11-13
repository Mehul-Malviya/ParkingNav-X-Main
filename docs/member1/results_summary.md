# Results Summary — Member 1

**Generated:** 2026-10-27 18:50 UTC  
**Script:** `scripts/generate_results_summary.py`  
**Source:** `runs/{{scenario_id}}/{{strategy}}/seed_*/metrics.json`  
**Seeds:** 30 per scenario × strategy (seeds 0–29)  
**CI:** 95% (1.96 σ/√n)

---

## 5-Metric Table (mean ± 95%CI)

| Scenario | v | dur | St | search (min) | wait (min) | gq avg | gq max | overflow | travel_t (min) | travel_d (m) | rej |
|----------|---|-----|----|--------------|-----------:|-------:|-------:|---------:|---------------:|-------------:|----:|
| E1 normal_day | 400 | 600 | B1 | 6.65±0.37 | 0.00±0.00 | 0.00±0.00 | 0.50 | 7.6±1.2 | 1.81±0.01 | 1009±5 | 0.0 |
| E1 normal_day | 400 | 600 | B2 | 2.54±0.00 | 0.00±0.00 | 0.00±0.00 | 0.00 | 0.0±0.0 | 0.68±0.00 | 378±— | 0.0 |
| E2 event_placement | 470 | 600 | B1 | 5.11±0.53 | 0.00±0.00 | 0.00±0.00 | 0.90 | 12.6±1.4 | 1.71±0.01 | 950±5 | 0.0 |
| E5 noise_0% | 400 | 600 | B1 | 6.64±1.01 | 0.00±0.00 | 0.00±0.00 | 0.80 | 7.6±4.1 | 1.81±0.01 | 1014±12 | 0.0 |
| E5 noise_10% | 400 | 600 | B1 | 6.64±1.01 | 0.00±0.00 | 0.00±0.00 | 0.80 | 7.6±4.1 | 1.81±0.01 | 1014±12 | 0.0 |
| E5 noise_20% | 400 | 600 | B1 | 6.64±1.01 | 0.00±0.00 | 0.00±0.00 | 0.80 | 7.6±4.1 | 1.81±0.01 | 1014±12 | 0.0 |
| road_closure | 400 | 600 | B1 | 5.74±0.00 | 0.00±0.00 | 0.00±0.00 | 0.00 | 4.0±0.0 | 1.97±0.00 | 1062±— | 0.0 |
| road_closure | 400 | 600 | B2 | 3.12±0.00 | 0.00±0.00 | 0.00±0.00 | 0.00 | 2.0±0.0 | 1.12±0.00 | 614±— | 0.0 |

---

## Notes

**wait and gate-queue are identical for B1 and B2** in most scenarios because both strategies
only choose *which lot* to assign — they do not control *which gate* a vehicle uses.
Gate assignment is random (uniform over open gates). Wait time and gate queue are gate-level
metrics; they can only improve with gate guidance (Member 3's optimizer).

**parking_full** is a stress scenario with a non-standard duration (90 min vs 600 min for
E1-E5, E7, road_closure). Its search/travel numbers are not directly comparable to the others;
it is the only scenario with real rejections (overflow = rejected).

**B3** (`PredictionOnlyStrategy`) and **P** (`ParkingNavXFullStrategy`) are in `demo_strategies.py`.
P is the full ParkingNav-X strategy with prediction, gate load balancing, and uncertainty hedging.

**E6 ablation A-D** vary the ablation flags (use_prediction, use_optimization, use_uncertainty,
proactive) wired into the scenario YAML and consumed by P strategy's `update_policy()` call.

**E5 noise equivalence (computed):**
B1: noise_0%=6.6400  noise_10%=6.6400  noise_20%=6.6400 (identical)
Current strategies are reactive (no forecast), so the noise parameter has no effect. Results
become meaningful once Member 3's optimizer consumes the noisy forecast.

**E7_replay** results use synthetic observations (real counting day data pending Member 5).

---

*Regenerate with:* `python scripts/generate_results_summary.py`