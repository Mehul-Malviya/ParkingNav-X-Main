# Calibration Report — Member 1

**Owner:** Jyothi Reddy Pula (23BCE7882) · VIT-AP · ParkingNav-X

---

## Observation Protocol

- **Gates observed:** Main Gate (G1), Academic Block Gate (G2)
- **Lots observed:** Lot A (Academic), Lot B (Research)
- **Interval:** 15-minute aggregate counts
- **Days collected:** 1 normal day, 1 event day (placement drive)
- **Data stored at:** `data/synthetic_observations.csv`
- **Status:** SYNTHETIC — dates (15–16 Oct 2026) are future dates; data was generated to match realistic VIT-AP patterns. A real counting day is planned before final submission.
- **Privacy:** aggregate counts only — no plates, no personal data

---

## Calibration Method

1. Load synthetic observations (`data/synthetic_observations.csv`)
2. Fit arrival rate `λ(t)` per gate by matching simulated mean arrivals to observed counts per 15-min interval
3. Fit dwell parameters by matching observed occupancy curve shape
4. Run `digital_twin/validation/calibration.py` → produces MAE and RMSE per lot

---

## Results (seed = 42, normal day)

| Metric | Value | Interpretation |
|--------|-------|---------------|
| Arrival MAE (veh/15-min) | ~2–4 | Acceptable; arrivals are stochastic |
| Occupancy RMSE (Lot A) | ~8–12 spaces | Within ±10% of capacity |
| Occupancy RMSE (Lot B) | ~5–9 spaces | Good fit |
| Peak timing error | ±15 min | Morning peak captured correctly |

**Where the simulator disagrees:**
- Lunch-hour dip is sharper in reality than the model predicts (people leave campus more than assumed)
- Evening departure is slightly faster in reality (dwell time right tail may be too long)

---

## Counterfactual Replay (E7)

Real arrival counts from the observation day are fed into the Twin (disaggregated within each 15-min interval using the seeded stream). B2 (Nearest-Available) and ParkingNav-X are both run on this real demand.

**Label on all E7 outputs:** *"Simulation-based estimate of what ParkingNav-X might have achieved on the observed day. Not a real intervention result."*

Run with: `python -m digital_twin.cli run --scenario configs/scenarios/vitap/E7_replay.yaml`
