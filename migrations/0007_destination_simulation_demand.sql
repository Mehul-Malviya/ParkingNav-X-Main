-- Whether a destination takes part in seeded simulation demand. The engine draws each
-- vehicle's destination from this table, so adding a destination changes every seeded
-- result; new destinations (e.g. LH-3) start excluded so committed experiments stay
-- reproducible. Set include_in_simulation: true in the campus YAML and re-run experiments to include.
ALTER TABLE destinations ADD COLUMN simulation_demand INTEGER NOT NULL DEFAULT 1;
