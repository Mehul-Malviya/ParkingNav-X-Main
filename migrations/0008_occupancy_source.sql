-- Migration 0008: record where each occupancy row came from, so real counts
-- (sensor / manual) can be told apart from simulation output and synthetic data.
-- Existing rows predate this column and stay 'unknown'.
ALTER TABLE lot_occupancy_history ADD COLUMN source TEXT NOT NULL DEFAULT 'unknown';
CREATE INDEX IF NOT EXISTS idx_lot_occ_source ON lot_occupancy_history (source, lot_id, recorded_at);
