-- Migration: Add time-series history tables for occupancy, gate queue, and road state
-- These tables store complete history of campus state observations
-- Allows multiple records per lot/gate/road (one per timestamp)

-- Parking lot occupancy history
CREATE TABLE IF NOT EXISTS parking_lot_state_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    parking_lot_id TEXT NOT NULL,
    occupied_spaces INTEGER NOT NULL,
    available_spaces INTEGER NOT NULL,
    occupancy_percentage REAL NOT NULL,
    predicted_occupancy TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    observation_timestamp TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id),
    UNIQUE (campus_id, parking_lot_id, observation_timestamp)
);

-- Gate state history (queue, throughput)
CREATE TABLE IF NOT EXISTS gate_state_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    current_queue_length INTEGER NOT NULL DEFAULT 0,
    throughput_last_5min INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    observation_timestamp TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id),
    UNIQUE (campus_id, gate_id, observation_timestamp)
);

-- Road state history (congestion, vehicle load)
CREATE TABLE IF NOT EXISTS road_state_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    road_id TEXT NOT NULL,
    current_load INTEGER NOT NULL DEFAULT 0,
    congestion_level TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'open',
    observation_timestamp TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id),
    UNIQUE (campus_id, road_id, observation_timestamp)
);

-- Create indexes for efficient time-series queries
CREATE INDEX IF NOT EXISTS idx_parking_lot_state_history_campus_timestamp
ON parking_lot_state_history(campus_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_parking_lot_state_history_lot_timestamp
ON parking_lot_state_history(parking_lot_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_gate_state_history_campus_timestamp
ON gate_state_history(campus_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_gate_state_history_gate_timestamp
ON gate_state_history(gate_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_road_state_history_campus_timestamp
ON road_state_history(campus_id, observation_timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_road_state_history_road_timestamp
ON road_state_history(road_id, observation_timestamp DESC);
