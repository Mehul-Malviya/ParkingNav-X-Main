-- Migration 0005: Tables for prediction, risk, recommendations, and experiments
-- Applied automatically by digital_twin/db.py on first connection.

-- Lot occupancy history (for risk engine and prediction)
CREATE TABLE IF NOT EXISTS lot_occupancy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL,
    occupied_spaces INTEGER NOT NULL,
    fill_rate REAL NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_lot_occ_history ON lot_occupancy_history (lot_id, recorded_at);

-- Gate queue history
CREATE TABLE IF NOT EXISTS gate_queue_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gate_id TEXT NOT NULL,
    queue_length INTEGER NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_gate_queue_history ON gate_queue_history (gate_id, recorded_at);

-- Occupancy predictions
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id TEXT NOT NULL,
    horizon_minutes INTEGER NOT NULL,
    model TEXT NOT NULL,
    predicted_fill_rate REAL NOT NULL,
    lower_90 REAL NOT NULL,
    upper_90 REAL NOT NULL,
    actual_fill_rate REAL,
    predicted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_predictions_lot ON predictions (lot_id, predicted_at);

-- Risk scores
CREATE TABLE IF NOT EXISTS risk_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,        -- lot_id, gate_id, road_id, or 'network'
    entity_type TEXT NOT NULL,      -- 'lot', 'gate', 'road', 'network'
    risk_type TEXT NOT NULL,        -- 'overflow', 'gate_queue', 'congestion', 'search', 'network'
    score REAL NOT NULL,
    severity TEXT NOT NULL,
    computed_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_risk_scores ON risk_scores (entity_id, computed_at);

-- Parking recommendations
CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    priority TEXT NOT NULL,         -- 'CRITICAL', 'HIGH', 'INFO'
    rec_type TEXT NOT NULL,
    lot_id TEXT,
    message TEXT NOT NULL,
    current_fill REAL,
    forecast_fill REAL,
    cost_J REAL,
    weight_profile TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    acknowledged_at TEXT
);

-- Experiment run registry
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    scenario TEXT NOT NULL,
    strategy TEXT NOT NULL,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending, running, done, failed
    started_at TEXT,
    completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_exp_runs ON experiment_runs (scenario, strategy, seed);

-- Experiment metrics (one row per run)
CREATE TABLE IF NOT EXISTS experiment_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
    total_vehicles INTEGER,
    parked_vehicles INTEGER,
    overflow_events INTEGER,
    avg_search_time_min REAL,
    avg_wait_time_min REAL,
    avg_gate_queue REAL,
    max_gate_queue INTEGER,
    cost_J REAL
);
CREATE INDEX IF NOT EXISTS idx_exp_metrics ON experiment_metrics (run_id);
