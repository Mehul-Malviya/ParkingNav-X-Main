"""
Part 8 — Build calibration dataset, run simulation, compute MAE/RMSE, save overlay plot.

Usage:
    python scripts/build_part8_calibration.py

Outputs:
    data/observations/vitap_observations.csv   — transformed observations (Part 8 schema)
    data/part8_calibration_results.json        — MAE, RMSE, bias per lot per day type
    docs/member1/calibration_overlay.png       — simulated vs observed occupancy overlay
"""

import csv
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Step 1: Transform synthetic_multi_year_demand.csv → Part 8 schema ─────────

EVENT_INTENSITY_MAP = {
    "none": 1.0, "normal": 1.0,
    "placement": 1.8, "exam": 1.5,
    "sports": 1.6, "fest": 2.0,
    "graduation": 2.2, "other": 1.4,
}

src = ROOT / "data" / "synthetic_multi_year_demand.csv"
out_obs = ROOT / "data" / "observations" / "vitap_observations.csv"

print("Step 1: Transforming synthetic_multi_year_demand.csv → Part 8 schema...")

with open(src, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

transformed = []
for r in rows:
    etype = r.get("event_type", "none").strip().lower()
    transformed.append({
        "timestamp":       r["timestamp"].replace("Z", "+00:00"),
        "gate_id":         r["gate_id"],
        "vehicle_count":   int(r["vehicle_arrivals"]),   # arrivals per 15-min = vehicle_count
        "parking_lot_id":  r["lot_id"],
        "occupied_spaces": int(r["occupied_spaces"]),
        "event_type":      etype if etype != "none" else "normal",
        "event_intensity": EVENT_INTENSITY_MAP.get(etype, 1.0),
        "notes":           r.get("notes", "") + " [source:synthetic]",
        "source":          "synthetic",
        "capacity":        int(r["total_capacity"]),
    })

out_obs.parent.mkdir(parents=True, exist_ok=True)
COLS = ["timestamp", "gate_id", "vehicle_count", "parking_lot_id",
        "occupied_spaces", "event_type", "event_intensity", "notes", "source", "capacity"]
with open(out_obs, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=COLS)
    writer.writeheader()
    writer.writerows(transformed)

print(f"  Written {len(transformed)} rows → {out_obs}")

# Separate normal day and event day
normal_rows = [r for r in transformed if r["event_type"] == "normal"]
event_rows  = [r for r in transformed if r["event_type"] != "normal"]
print(f"  Normal day rows: {len(normal_rows)}  |  Event day rows: {len(event_rows)}")

# ── Step 2: Run simulation for calibration day (2024-01-15 normal day) ────────

print("\nStep 2: Running simulation for calibration day (2024-01-15, seed=7)...")

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.simulation.engine import SimulationEngine
from digital_twin.simulation.scenario import ScenarioLoader
from digital_twin.simulation.strategy import FirstAvailableStrategy

conn = get_connection(":memory:")
apply_migrations(conn)
load_campus_config(ROOT / "configs" / "campus" / "vitap.yaml", conn)

# Use E1 normal day scenario (matches 2024-01-15 profile)
# B1 (FirstAvailable) fills academic-main first (config order: academic → hostel → …),
# matching the synthetic observations which track academic-main occupancy.
scenario = ScenarioLoader.load(ROOT / "configs" / "scenarios" / "vitap" / "E1_normal_day.yaml")
scenario.random_seed = 7

engine = SimulationEngine(runs_dir=tempfile.mkdtemp())
result = engine.run(scenario, FirstAvailableStrategy(), conn)
print(f"  Run complete: {result.secondary_metrics['total_vehicles_simulated']} vehicles, "
      f"runtime={result.runtime_sec:.1f}s")

# ── Step 3: Extract simulated occupancy per 15-min interval ───────────────────

print("\nStep 3: Extracting simulated occupancy at 15-min intervals...")

# result.timesteps stores 1 entry per simulation minute (not per 10s tick)
# 600 entries == 600 minutes; so 15-min window = 15 entries
ticks_per_15m = 15

lot_ids = sorted(set(
    k.replace("parking_occupancy_", "")
    for k in (result.timesteps[0] if result.timesteps else {})
    if k.startswith("parking_occupancy_")
))

# Read lot capacities directly from the DB (timesteps don't carry capacity)
lot_caps = {}
for row in conn.execute("SELECT parking_lot_id, total_capacity FROM parking_lots"):
    lot_caps[row["parking_lot_id"]] = row["total_capacity"]

sim_by_interval = []  # [{interval_idx, lot_id, simulated_occupied, simulated_occ_pct}]
n_intervals = math.ceil(len(result.timesteps) / ticks_per_15m)

for i in range(n_intervals):
    start = i * ticks_per_15m
    end   = min(start + ticks_per_15m, len(result.timesteps))
    window = result.timesteps[start:end]
    if not window:
        continue
    for lot_id in lot_ids:
        occ_key = f"parking_occupancy_{lot_id}"
        occ_vals = [ts.get(occ_key, 0) for ts in window]
        cap_val  = lot_caps.get(lot_id, 1) or 1
        avg_occ  = sum(occ_vals) / len(occ_vals)
        sim_by_interval.append({
            "interval_idx":      i,
            "lot_id":            lot_id,
            "simulated_occupied": round(avg_occ, 2),
            "simulated_occ_pct": round(avg_occ / cap_val * 100, 2),
            "capacity":          cap_val,
        })

print(f"  {len(sim_by_interval)} simulated data points across {n_intervals} intervals × {len(lot_ids)} lots")

# ── Step 4: Align observed vs simulated, compute MAE / RMSE ───────────────────

print("\nStep 4: Computing calibration metrics (MAE, RMSE, bias)...")

# Use academic-main lot for primary calibration (most data in synthetic file)
PRIMARY_LOT = "vitap-lot-academic-main"

obs_primary = [r for r in normal_rows if r["parking_lot_id"] == PRIMARY_LOT]
obs_primary.sort(key=lambda r: r["timestamp"])

# Match by interval index (both start at tick 0 = 08:00)
# Observations start at 08:00; scenario start_time_min=480 (08:00), so interval 0 = 08:00
# Both start at the same point — align directly by position
n_match = min(len(obs_primary), n_intervals)

real_occ  = [int(obs_primary[i]["occupied_spaces"])   for i in range(n_match)]
real_cap  = [int(obs_primary[i]["capacity"])           for i in range(n_match)]
real_pct  = [real_occ[i] / max(real_cap[i], 1) * 100  for i in range(n_match)]

sim_primary = {d["interval_idx"]: d for d in sim_by_interval if d["lot_id"] == PRIMARY_LOT}
sim_occ  = [sim_primary.get(i, {}).get("simulated_occupied", 0)  for i in range(n_match)]
sim_cap  = [sim_primary.get(i, {}).get("capacity", 1) or 1        for i in range(n_match)]
sim_pct  = [sim_occ[i] / sim_cap[i] * 100                         for i in range(n_match)]

def mae(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a) if a else 0.0

def rmse(a, b):
    return math.sqrt(sum((x - y)**2 for x, y in zip(a, b)) / len(a)) if a else 0.0

def bias(a, b):   # b - a  (sim - real)
    return sum(y - x for x, y in zip(a, b)) / len(a) if a else 0.0

mae_occ  = mae(real_occ,  sim_occ)
rmse_occ = rmse(real_occ, sim_occ)
bias_occ = bias(real_occ, sim_occ)
mae_pct  = mae(real_pct,  sim_pct)
rmse_pct = rmse(real_pct, sim_pct)

print(f"  Lot: {PRIMARY_LOT}  |  Matched intervals: {n_match}")
print(f"  Occupied spaces — MAE: {mae_occ:.2f}  RMSE: {rmse_occ:.2f}  Bias: {bias_occ:+.2f}")
print(f"  Occupancy pct   — MAE: {mae_pct:.2f}%  RMSE: {rmse_pct:.2f}%")

# ── Step 5: Save calibration results JSON ─────────────────────────────────────

cal_results = {
    "calibration_date": "2024-01-15",
    "scenario_used": "E1_normal_day",
    "seed": 7,
    "strategy": "B1-FirstAvailable",
    "primary_lot": PRIMARY_LOT,
    "matched_intervals": n_match,
    "data_source": "synthetic (labeled; replace with real counts before final submission)",
    "metrics": {
        "occupied_spaces": {
            "MAE":  round(mae_occ,  2),
            "RMSE": round(rmse_occ, 2),
            "bias": round(bias_occ, 2),
        },
        "occupancy_pct": {
            "MAE":  round(mae_pct,  2),
            "RMSE": round(rmse_pct, 2),
        },
    },
    "interpretation": (
        f"Simulator reproduces observed occupancy with MAE={mae_occ:.1f} spaces "
        f"({mae_pct:.1f}% occupancy) on the academic lot for a normal day. "
        f"Bias={bias_occ:+.1f} spaces ({'over' if bias_occ > 0 else 'under'}estimates). "
        "Data source is synthetic; values will be updated with real campus counts."
    ),
    "series": {
        "intervals": list(range(n_match)),
        "real_occupied": real_occ,
        "sim_occupied":  [round(x, 1) for x in sim_occ],
        "real_pct":      [round(x, 1) for x in real_pct],
        "sim_pct":       [round(x, 1) for x in sim_pct],
    }
}

out_json = ROOT / "data" / "part8_calibration_results.json"
with open(out_json, "w") as f:
    json.dump(cal_results, f, indent=2)
print(f"\n  Calibration JSON → {out_json}")

# ── Step 6: Overlay plot ───────────────────────────────────────────────────────

print("\nStep 6: Generating overlay plot...")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    intervals = list(range(n_match))
    # Convert interval index to HH:MM labels (start 08:00, 15-min steps)
    def idx_to_time(i):
        total_min = 8 * 60 + i * 15
        return f"{total_min // 60:02d}:{total_min % 60:02d}"
    labels = [idx_to_time(i) for i in intervals]
    tick_every = max(1, n_match // 12)  # show ~12 labels

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(
        "Part 8 — Simulated vs Observed Occupancy\n"
        f"VIT-AP Campus · {PRIMARY_LOT} · Normal Day (2024-01-15) · seed=7",
        fontsize=13, fontweight="bold"
    )

    # Top: absolute occupancy
    ax1.plot(intervals, real_occ, "o-", color="#2196F3", label="Observed (synthetic)", linewidth=2, markersize=4)
    ax1.plot(intervals, sim_occ,  "s--", color="#F44336", label="Simulated (B1-FirstAvailable)", linewidth=2, markersize=4)
    ax1.set_ylabel("Occupied Spaces")
    ax1.set_title(f"Occupied Spaces — MAE={mae_occ:.1f} spaces, RMSE={rmse_occ:.1f}, Bias={bias_occ:+.1f}")
    ax1.legend()
    ax1.set_xticks(intervals[::tick_every])
    ax1.set_xticklabels(labels[::tick_every], rotation=45, ha="right", fontsize=8)
    ax1.grid(True, alpha=0.3)

    # Bottom: occupancy pct
    ax2.plot(intervals, real_pct, "o-", color="#2196F3", label="Observed %", linewidth=2, markersize=4)
    ax2.plot(intervals, sim_pct,  "s--", color="#F44336", label="Simulated %", linewidth=2, markersize=4)
    ax2.set_ylabel("Occupancy %")
    ax2.set_xlabel("Time of Day")
    ax2.set_title(f"Occupancy % — MAE={mae_pct:.1f}%, RMSE={rmse_pct:.1f}%")
    ax2.set_ylim(0, 105)
    ax2.legend()
    ax2.set_xticks(intervals[::tick_every])
    ax2.set_xticklabels(labels[::tick_every], rotation=45, ha="right", fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_png = ROOT / "docs" / "member1" / "calibration_overlay.png"
    plt.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Overlay plot → {out_png}")

except ImportError:
    print("  matplotlib not installed — skipping plot (JSON results still saved)")
    out_png = None

# ── Step 7: Print summary ──────────────────────────────────────────────────────

print("\n" + "="*60)
print("PART 8 CALIBRATION SUMMARY")
print("="*60)
print(f"  Observations file : {out_obs}  ({len(transformed)} rows)")
print(f"  Normal day rows   : {len(normal_rows)}")
print(f"  Event day rows    : {len(event_rows)}")
print(f"  Calibration lot   : {PRIMARY_LOT}")
print(f"  Matched intervals : {n_match} × 15 min")
print(f"  MAE  (spaces)     : {mae_occ:.2f}")
print(f"  RMSE (spaces)     : {rmse_occ:.2f}")
print(f"  Bias (spaces)     : {bias_occ:+.2f}")
print(f"  MAE  (pct)        : {mae_pct:.2f}%")
print(f"  RMSE (pct)        : {rmse_pct:.2f}%")
print(f"  Results JSON      : {out_json}")
if out_png:
    print(f"  Overlay plot      : {out_png}")
print("="*60)
print("Part 8 prototype complete.")
