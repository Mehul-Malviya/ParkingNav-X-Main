-- Tracks which configured EVENTS rows are currently active for a campus,
-- so apply_event_state() has real persisted state to toggle rather than
-- being a no-op stub. Added as a new migration per rule 9 -- 0001 is
-- never rewritten.

CREATE TABLE IF NOT EXISTS active_events (
    campus_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    activated_at TEXT NOT NULL,
    deactivated_at TEXT,
    PRIMARY KEY (campus_id, event_id)
);
