# ParkingNav-X Review-Day Demo Script (PowerShell)
# Run from the repository root: .\scripts\demo.ps1
# All data is SYNTHETIC — this is an academic prototype.

$BASE = "http://localhost:8000"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  ParkingNav-X -- Review Demo"
Write-Host "  VIT-AP University Capstone 2026-27"
Write-Host "  All data is SYNTHETIC"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

function Invoke-Step($num, $desc, $uri, $method = "GET", $body = $null) {
    Write-Host "Step $num`: $desc" -ForegroundColor Yellow
    try {
        if ($body) {
            $resp = Invoke-RestMethod -Uri $uri -Method $method -Body ($body | ConvertTo-Json) -ContentType "application/json"
        } else {
            $resp = Invoke-RestMethod -Uri $uri -Method $method
        }
        $resp | ConvertTo-Json -Depth 6
    } catch {
        Write-Host "ERROR: $_" -ForegroundColor Red
    }
    Write-Host ""
}

# STEP 1: Health check
Write-Host "Step 1: Checking backend health..." -ForegroundColor Yellow
try {
    $health = Invoke-RestMethod -Uri "$BASE/" -Method GET
    $health | ConvertTo-Json
} catch {
    Write-Host ""
    Write-Host "ERROR: Backend is not running." -ForegroundColor Red
    Write-Host "Start it with:" -ForegroundColor White
    Write-Host "  uvicorn digital_twin.api.app:app --reload --port 8000" -ForegroundColor Green
    exit 1
}
Write-Host ""

# STEP 2: Campus Digital Twin state
Invoke-Step 2 "Campus Digital Twin state" "$BASE/campus"

# STEP 3: Run E2 placement-drive with ParkingNav-X
Invoke-Step 3 "Running E2 (placement drive) with ParkingNav-X strategy" `
    "$BASE/simulate" "POST" @{scenario="E2_event_placement"; strategy="P"}

# STEP 4: 15-minute forecast
Invoke-Step 4 "15-minute occupancy forecast (XGBoost + conformal intervals)" `
    "$BASE/predict/all?horizon_minutes=15"

# STEP 5: Risk assessment
Invoke-Step 5a "Current risk scores" "$BASE/risk/current"
Invoke-Step 5b "Forecast risk (15 min)" "$BASE/risk/forecast?horizon_minutes=15"

# STEP 6: Proactive recommendation
Invoke-Step 6 "ParkingNav-X recommendation (objective score + why_chosen)" `
    "$BASE/recommendations"

# STEP 7: Strategy comparison
Invoke-Step 7 "Strategy comparison: B1 vs B2 vs B3 vs P on E1" `
    "$BASE/compare/E1_normal_day"

# STEP 8: Experiment summary
Invoke-Step 8 "Stored experiment results summary" "$BASE/experiments/summary"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "  Demo complete."
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  API docs:  http://localhost:8000/docs"
Write-Host "==============================================" -ForegroundColor Cyan

Write-Host ""
Write-Host "-- Troubleshooting --" -ForegroundColor Gray
Write-Host "Port 8000 in use: netstat -ano | findstr :8000 -> kill by PID"
Write-Host "Port 5173 in use: netstat -ano | findstr :5173 -> kill by PID"
Write-Host "Missing deps:     pip install -r requirements.txt"
Write-Host "Missing npm:      cd frontend; npm install"
Write-Host ""
Write-Host "-- Fallback (no live backend) --" -ForegroundColor Gray
Write-Host "Open: experiments\results\summary_table.md"
Write-Host "Open: experiments\results\prediction_metrics.json"
Write-Host "These are real saved results from prior runs."
