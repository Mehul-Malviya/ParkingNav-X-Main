-- Adds a place to persist a simulation run's final metrics (previously
-- only written to Parquet on disk), so the API can serve them back
-- without re-reading files. New migration, 0001/0002 untouched.

ALTER TABLE simulation_runs ADD COLUMN metrics_json TEXT;
ALTER TABLE simulation_runs ADD COLUMN overflow_events_json TEXT;
