#!/usr/bin/env bash
# ParkingNav-X Review-Day Demo Script (bash)
# Run from the repository root: bash scripts/demo.sh
# All data is SYNTHETIC — this is an academic prototype.

set -e

BASE="http://localhost:8000"

echo "=============================================="
echo "  ParkingNav-X — Review Demo"
echo "  VIT-AP University Capstone 2026-27"
echo "  All data is SYNTHETIC"
echo "=============================================="
echo ""

# STEP 1: Verify backend is running
echo "Step 1: Checking backend health..."
curl -s "$BASE/" | python -m json.tool || {
  echo ""
  echo "ERROR: Backend is not running."
  echo "Start it with: uvicorn digital_twin.api.app:app --reload --port 8000"
  exit 1
}
echo ""

# STEP 2: Load campus state
echo "Step 2: Campus Digital Twin state..."
curl -s "$BASE/campus" | python -m json.tool
echo ""

# STEP 3: Run placement-drive scenario (E2) with ParkingNav-X strategy
echo "Step 3: Running E2 (placement drive) with ParkingNav-X strategy..."
curl -s -X POST "$BASE/simulate" \
  -H "Content-Type: application/json" \
  -d '{"scenario": "E2_event_placement", "strategy": "P"}' | python -m json.tool
echo ""

# STEP 4: Get 15-minute occupancy forecast
echo "Step 4: 15-minute occupancy forecast (XGBoost + conformal intervals)..."
curl -s "$BASE/predict/all?horizon_minutes=15" | python -m json.tool
echo ""

# STEP 5: Current and forecast risk
echo "Step 5: Risk assessment..."
curl -s "$BASE/risk/current" | python -m json.tool
curl -s "$BASE/risk/forecast?horizon_minutes=15" | python -m json.tool
echo ""

# STEP 6: Proactive recommendation
echo "Step 6: ParkingNav-X recommendation (with objective score and why_chosen)..."
curl -s "$BASE/recommendations" | python -m json.tool
echo ""

# STEP 7: Strategy comparison on E1
echo "Step 7: Strategy comparison — B1 vs B2 vs B3 vs P on E1 (normal day)..."
curl -s "$BASE/compare/E1_normal_day" | python -m json.tool
echo ""

# STEP 8: Experiment summary (precomputed results)
echo "Step 8: Experiment results summary..."
curl -s "$BASE/experiments/summary" | python -m json.tool
echo ""

echo "=============================================="
echo "  Demo complete."
echo "  Frontend: http://localhost:5173"
echo "  API docs: http://localhost:8000/docs"
echo "=============================================="

# ── Troubleshooting ─────────────────────────────────
# Port 8000 already in use:
#   lsof -i :8000 | grep LISTEN   (find PID)
#   kill <PID>
#
# Port 5173 already in use:
#   lsof -i :5173 | grep LISTEN
#   kill <PID>
#
# Missing Python dependency:
#   pip install -r requirements.txt
#
# Missing npm packages:
#   cd frontend && npm install
#
# Fallback (precomputed results, no live backend needed):
#   Open experiments/results/summary_table.md
#   Open experiments/results/prediction_metrics.json
#   These are real saved results from prior runs.
