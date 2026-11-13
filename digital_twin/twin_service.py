"""
Part 3: Digital Twin State -- the live, continuously-updating state of the
campus. This represents STATE (occupied/available/freshness), not the map.
Everyone reads from this; Member 2's data collection writes real
observations into it through the same validated update_* methods this
module's simulation engine uses (distinguished only by provenance/source).
"""

import json
from datetime import datetime, timezone

from digital_twin.models import FRESHNESS_THRESHOLDS_MINUTES, FreshnessState, Provenance


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _validate_provenance(provenance) -> None:
    """Never ambiguous: provenance must be one of the known values, not
    just any non-empty string."""
    if provenance not in {p.value for p in Provenance}:
        raise ValueError(
            f"Unknown provenance '{provenance}'. Must be one of: "
            f"{', '.join(p.value for p in Provenance)}."
        )


def compute_freshness(observation_timestamp: str, entity_type: str, now: datetime = None) -> str:
    if not observation_timestamp:
        return FreshnessState.UNKNOWN.value
    now = now or datetime.now(timezone.utc)
    age_minutes = (now - _parse_ts(observation_timestamp)).total_seconds() / 60.0
    fresh_below, aging_below = FRESHNESS_THRESHOLDS_MINUTES.get(entity_type, (10, 30))
    if age_minutes < fresh_below:
        return FreshnessState.FRESH.value
    if age_minutes < aging_below:
        return FreshnessState.AGING.value
    return FreshnessState.STALE.value


class DigitalTwinService:
    """Digital Twin State Manager with full audit trail, snapshots, forks, and invariant checking."""

    def __init__(self, debug_mode: bool = False):
        """debug_mode=True: check_invariants() runs after every transition."""
        self.debug_mode = debug_mode

    def initialize_state(self, campus_id: str, conn):
        """Sets every entity for this campus to no-data (deletes any
        existing current-state rows; history/snapshots are untouched)."""
        for table in ("parking_lot_state", "gate_state", "road_state", "vehicle_state"):
            conn.execute(f"DELETE FROM {table} WHERE campus_id=?", (campus_id,))
        conn.commit()

    def seed_from_config(self, campus_id: str, conn):
        """Seed live state from campus config tables (all lots open, occupied=0).

        Gives the Digital Twin a valid baseline state without needing real
        sensors. Represents campus at start-of-day before any vehicles arrive.
        """
        ts = datetime.now(timezone.utc).isoformat()
        lots = conn.execute(
            "SELECT parking_lot_id FROM parking_lots WHERE campus_id=? AND status='open'",
            (campus_id,)
        ).fetchall()
        for row in lots:
            self.update_parking_state(
                campus_id, row["parking_lot_id"],
                occupied_spaces=0,
                source="config_baseline",
                provenance="SYNTHETIC",
                observation_timestamp=ts,
                conn=conn,
                commit=False,
            )
        gates = conn.execute(
            "SELECT gate_id FROM gates WHERE campus_id=? AND status='open'",
            (campus_id,)
        ).fetchall()
        for row in gates:
            self.update_gate_state(
                campus_id, row["gate_id"],
                current_queue_length=0,
                throughput_last_5min=0,
                source="config_baseline",
                provenance="SYNTHETIC",
                observation_timestamp=ts,
                conn=conn,
                commit=False,
            )
        conn.commit()

    def update_parking_state(self, campus_id, lot_id, occupied_spaces, source, provenance,
                              observation_timestamp, conn, now: datetime = None, commit: bool = True):
        if not source or not provenance:
            raise ValueError("Both 'source' and 'provenance' are required for a parking state update.")
        _validate_provenance(provenance)

        lot = conn.execute(
            "SELECT usable_capacity FROM parking_lots WHERE campus_id=? AND parking_lot_id=?",
            (campus_id, lot_id),
        ).fetchone()
        if not lot:
            raise ValueError(f"Unknown parking lot '{lot_id}' for campus '{campus_id}'.")

        usable_capacity = lot["usable_capacity"]
        if occupied_spaces > usable_capacity:
            raise ValueError(
                f"Rejected: occupied_spaces ({occupied_spaces}) exceeds usable_capacity "
                f"({usable_capacity}) for parking lot '{lot_id}'. State was NOT changed."
            )
        if occupied_spaces < 0:
            raise ValueError(f"Rejected: occupied_spaces cannot be negative for parking lot '{lot_id}'.")

        available_spaces = usable_capacity - occupied_spaces
        occupancy_percentage = round(100 * occupied_spaces / usable_capacity, 2) if usable_capacity else 0.0
        ingestion_timestamp = (now or datetime.now(timezone.utc)).isoformat()

        conn.execute(
            """INSERT INTO parking_lot_state (campus_id, parking_lot_id, occupied_spaces, available_spaces,
                 occupancy_percentage, predicted_occupancy, status, observation_timestamp, ingestion_timestamp,
                 source, provenance)
               VALUES (?, ?, ?, ?, ?, NULL, 'open', ?, ?, ?, ?)
               ON CONFLICT(campus_id, parking_lot_id) DO UPDATE SET
                 occupied_spaces=excluded.occupied_spaces, available_spaces=excluded.available_spaces,
                 occupancy_percentage=excluded.occupancy_percentage,
                 observation_timestamp=excluded.observation_timestamp,
                 ingestion_timestamp=excluded.ingestion_timestamp,
                 source=excluded.source, provenance=excluded.provenance""",
            (campus_id, lot_id, occupied_spaces, available_spaces, occupancy_percentage,
             observation_timestamp, ingestion_timestamp, source, provenance),
        )
        if commit:
            conn.commit()
        if self.debug_mode:
            errors = self.check_invariants(campus_id, conn)
            if errors:
                raise AssertionError(f"Invariant violation after parking state update: {errors}")
        return self.get_parking_state(campus_id, lot_id, conn, now=now)

    def update_gate_state(self, campus_id, gate_id, current_queue_length, throughput_last_5min,
                           source, provenance, observation_timestamp, conn, now: datetime = None, commit: bool = True):
        if not source or not provenance:
            raise ValueError("Both 'source' and 'provenance' are required for a gate state update.")
        _validate_provenance(provenance)
        if current_queue_length < 0:
            raise ValueError(f"Rejected: current_queue_length cannot be negative for gate '{gate_id}'.")

        gate = conn.execute(
            "SELECT gate_id FROM gates WHERE campus_id=? AND gate_id=?", (campus_id, gate_id)
        ).fetchone()
        if not gate:
            raise ValueError(f"Unknown gate '{gate_id}' for campus '{campus_id}'.")

        ingestion_timestamp = (now or datetime.now(timezone.utc)).isoformat()
        conn.execute(
            """INSERT INTO gate_state (campus_id, gate_id, current_queue_length, throughput_last_5min,
                 status, observation_timestamp, ingestion_timestamp, source, provenance)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
               ON CONFLICT(campus_id, gate_id) DO UPDATE SET
                 current_queue_length=excluded.current_queue_length,
                 throughput_last_5min=excluded.throughput_last_5min,
                 observation_timestamp=excluded.observation_timestamp,
                 ingestion_timestamp=excluded.ingestion_timestamp,
                 source=excluded.source, provenance=excluded.provenance""",
            (campus_id, gate_id, current_queue_length, throughput_last_5min,
             observation_timestamp, ingestion_timestamp, source, provenance),
        )
        if commit:
            conn.commit()
        if self.debug_mode:
            errors = self.check_invariants(campus_id, conn)
            if errors:
                raise AssertionError(f"Invariant violation after gate state update: {errors}")
        return self._gate_state_row(campus_id, gate_id, conn, now=now)

    def update_road_state(self, campus_id, road_id, current_load, congestion_level,
                           source, provenance, observation_timestamp, conn, now: datetime = None, commit: bool = True):
        if not source or not provenance:
            raise ValueError("Both 'source' and 'provenance' are required for a road state update.")
        _validate_provenance(provenance)
        if current_load < 0:
            raise ValueError(f"Rejected: current_load cannot be negative for road '{road_id}'.")

        ingestion_timestamp = (now or datetime.now(timezone.utc)).isoformat()
        conn.execute(
            """INSERT INTO road_state (campus_id, road_id, current_load, congestion_level,
                 status, observation_timestamp, ingestion_timestamp, source, provenance)
               VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?)
               ON CONFLICT(campus_id, road_id) DO UPDATE SET
                 current_load=excluded.current_load, congestion_level=excluded.congestion_level,
                 observation_timestamp=excluded.observation_timestamp,
                 ingestion_timestamp=excluded.ingestion_timestamp,
                 source=excluded.source, provenance=excluded.provenance""",
            (campus_id, road_id, current_load, congestion_level,
             observation_timestamp, ingestion_timestamp, source, provenance),
        )
        if commit:
            conn.commit()
        if self.debug_mode:
            errors = self.check_invariants(campus_id, conn)
            if errors:
                raise AssertionError(f"Invariant violation after road state update: {errors}")

    def update_vehicle_state(self, campus_id, vehicle_id, state, source, timestamp, conn,
                              destination_id=None, assigned_parking_lot_id=None,
                              current_node_id=None, route=None, arrival_time=None, commit: bool = True):
        conn.execute(
            """INSERT INTO vehicle_state (campus_id, vehicle_id, arrival_time, destination_id,
                 assigned_parking_lot_id, current_node_id, route, state, source, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(campus_id, vehicle_id) DO UPDATE SET
                 destination_id=excluded.destination_id, assigned_parking_lot_id=excluded.assigned_parking_lot_id,
                 current_node_id=excluded.current_node_id, route=excluded.route, state=excluded.state,
                 source=excluded.source, timestamp=excluded.timestamp""",
            (campus_id, vehicle_id, arrival_time, destination_id, assigned_parking_lot_id,
             current_node_id, json.dumps(route) if route else None, state, source, timestamp),
        )
        if commit:
            conn.commit()
        if self.debug_mode:
            errors = self.check_invariants(campus_id, conn)
            if errors:
                raise AssertionError(f"Invariant violation after vehicle state update: {errors}")

    def get_parking_state(self, campus_id, lot_id, conn, now: datetime = None):
        row = conn.execute(
            "SELECT * FROM parking_lot_state WHERE campus_id=? AND parking_lot_id=?", (campus_id, lot_id)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["freshness_state"] = compute_freshness(d["observation_timestamp"], "parking", now=now)
        return d

    def _gate_state_row(self, campus_id, gate_id, conn, now: datetime = None):
        row = conn.execute(
            "SELECT * FROM gate_state WHERE campus_id=? AND gate_id=?", (campus_id, gate_id)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["freshness_state"] = compute_freshness(d["observation_timestamp"], "gate", now=now)
        return d

    def get_current_state(self, campus_id, conn, now: datetime = None):
        parking = [
            {**dict(r), "freshness_state": compute_freshness(r["observation_timestamp"], "parking", now=now)}
            for r in conn.execute("SELECT * FROM parking_lot_state WHERE campus_id=?", (campus_id,))
        ]
        gates = [
            {**dict(r), "freshness_state": compute_freshness(r["observation_timestamp"], "gate", now=now)}
            for r in conn.execute("SELECT * FROM gate_state WHERE campus_id=?", (campus_id,))
        ]
        roads = [
            {**dict(r), "freshness_state": compute_freshness(r["observation_timestamp"], "road", now=now)}
            for r in conn.execute("SELECT * FROM road_state WHERE campus_id=?", (campus_id,))
        ]
        vehicles = [dict(r) for r in conn.execute("SELECT * FROM vehicle_state WHERE campus_id=?", (campus_id,))]
        return {"campus_id": campus_id, "parking": parking, "gates": gates, "roads": roads, "vehicles": vehicles}

    def get_state_history(self, campus_id, from_ts, to_ts, conn):
        query = "SELECT * FROM campus_state_snapshot WHERE campus_id=?"
        params = [campus_id]
        if from_ts:
            query += " AND timestamp >= ?"
            params.append(from_ts)
        if to_ts:
            query += " AND timestamp <= ?"
            params.append(to_ts)
        query += " ORDER BY timestamp ASC"
        rows = conn.execute(query, params).fetchall()
        return [{**dict(r), "full_state": json.loads(r["full_state"])} for r in rows]

    def snapshot_now(self, campus_id, conn, timestamp: str = None):
        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        state = self.get_current_state(campus_id, conn)
        config_version_row = conn.execute(
            "SELECT active_configuration_version FROM campuses WHERE campus_id=?", (campus_id,)
        ).fetchone()
        config_version = config_version_row["active_configuration_version"] if config_version_row else None

        cursor = conn.execute(
            """INSERT INTO campus_state_snapshot (campus_id, timestamp, configuration_version, full_state)
               VALUES (?, ?, ?, ?)""",
            (campus_id, timestamp, config_version, json.dumps(state)),
        )
        conn.commit()
        return cursor.lastrowid

    def reset_state(self, campus_id, conn):
        """Testing/demo resets only."""
        for table in ("parking_lot_state", "gate_state", "road_state", "vehicle_state", "campus_state_snapshot"):
            conn.execute(f"DELETE FROM {table} WHERE campus_id=?", (campus_id,))
        conn.commit()

    def apply_event_state(self, campus_id, event_id, active, conn, timestamp: str = None):
        """Activates/deactivates a configured EVENTS row for this campus.
        Rejects an unknown event_id rather than silently no-opping. Does
        NOT decide what effect follows (demand multiplier application is
        the simulation engine's job, reading this + the event's own
        configured fields) -- this only tracks which event is currently on."""
        event = conn.execute(
            "SELECT event_id FROM events WHERE campus_id=? AND event_id=?", (campus_id, event_id)
        ).fetchone()
        if not event:
            raise ValueError(f"Unknown event '{event_id}' for campus '{campus_id}'.")

        timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        if active:
            conn.execute(
                """INSERT INTO active_events (campus_id, event_id, activated_at, deactivated_at)
                   VALUES (?, ?, ?, NULL)
                   ON CONFLICT(campus_id, event_id) DO UPDATE SET
                     activated_at=excluded.activated_at, deactivated_at=NULL""",
                (campus_id, event_id, timestamp),
            )
        else:
            conn.execute(
                "UPDATE active_events SET deactivated_at=? WHERE campus_id=? AND event_id=?",
                (timestamp, campus_id, event_id),
            )
        conn.commit()

    def get_active_events(self, campus_id, conn):
        rows = conn.execute(
            "SELECT * FROM active_events WHERE campus_id=? AND deactivated_at IS NULL", (campus_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def validate_state(self, campus_id, conn) -> list:
        """Structural re-check of whatever is currently stored -- a
        sanity pass, not a write path. Returns a list of error strings
        (empty = consistent)."""
        errors = []
        for row in conn.execute("SELECT * FROM parking_lot_state WHERE campus_id=?", (campus_id,)):
            lot = conn.execute(
                "SELECT usable_capacity FROM parking_lots WHERE campus_id=? AND parking_lot_id=?",
                (campus_id, row["parking_lot_id"]),
            ).fetchone()
            if lot and (row["occupied_spaces"] < 0 or row["occupied_spaces"] > lot["usable_capacity"]):
                errors.append(f"Inconsistent parking state for '{row['parking_lot_id']}'.")
        for row in conn.execute("SELECT * FROM gate_state WHERE campus_id=?", (campus_id,)):
            if row["current_queue_length"] < 0:
                errors.append(f"Inconsistent gate state for '{row['gate_id']}'.")
        for row in conn.execute("SELECT * FROM road_state WHERE campus_id=?", (campus_id,)):
            if row["current_load"] < 0:
                errors.append(f"Inconsistent road state for '{row['road_id']}'.")
        return errors

    def restore_snapshot(self, campus_id, snapshot_id, conn):
        """Overwrites CURRENT state with a prior snapshot's contents,
        preserving that snapshot's original provenance/source/timestamps
        rather than stamping them as new. For read-only inspection of a
        past state without mutating current state, use
        get_state_at_timestamp instead."""
        row = conn.execute(
            "SELECT * FROM campus_state_snapshot WHERE campus_id=? AND snapshot_id=?",
            (campus_id, snapshot_id),
        ).fetchone()
        if not row:
            raise ValueError(f"Unknown snapshot_id '{snapshot_id}' for campus '{campus_id}'.")

        full_state = json.loads(row["full_state"])
        for table in ("parking_lot_state", "gate_state", "road_state", "vehicle_state"):
            conn.execute(f"DELETE FROM {table} WHERE campus_id=?", (campus_id,))

        for p in full_state.get("parking", []):
            conn.execute(
                """INSERT INTO parking_lot_state (campus_id, parking_lot_id, occupied_spaces, available_spaces,
                     occupancy_percentage, predicted_occupancy, status, observation_timestamp,
                     ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, p["parking_lot_id"], p["occupied_spaces"], p["available_spaces"],
                 p["occupancy_percentage"], p.get("predicted_occupancy"), p["status"],
                 p["observation_timestamp"], p["ingestion_timestamp"], p["source"], p["provenance"]),
            )
        for g in full_state.get("gates", []):
            conn.execute(
                """INSERT INTO gate_state (campus_id, gate_id, current_queue_length, throughput_last_5min,
                     status, observation_timestamp, ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, g["gate_id"], g["current_queue_length"], g["throughput_last_5min"],
                 g["status"], g["observation_timestamp"], g["ingestion_timestamp"], g["source"], g["provenance"]),
            )
        for r in full_state.get("roads", []):
            conn.execute(
                """INSERT INTO road_state (campus_id, road_id, current_load, congestion_level,
                     status, observation_timestamp, ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, r["road_id"], r["current_load"], r["congestion_level"],
                 r["status"], r["observation_timestamp"], r["ingestion_timestamp"], r["source"], r["provenance"]),
            )
        for v in full_state.get("vehicles", []):
            conn.execute(
                """INSERT INTO vehicle_state (campus_id, vehicle_id, arrival_time, destination_id,
                     assigned_parking_lot_id, current_node_id, route, state, source, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, v["vehicle_id"], v.get("arrival_time"), v.get("destination_id"),
                 v.get("assigned_parking_lot_id"), v.get("current_node_id"), v.get("route"),
                 v["state"], v["source"], v["timestamp"]),
            )
        conn.commit()

    def get_state_at_timestamp(self, campus_id, timestamp, conn):
        """Read-only: the most recent snapshot at or before `timestamp`.
        Does not mutate current state -- use restore_snapshot for that."""
        row = conn.execute(
            """SELECT * FROM campus_state_snapshot
               WHERE campus_id=? AND timestamp <= ?
               ORDER BY timestamp DESC LIMIT 1""",
            (campus_id, timestamp),
        ).fetchone()
        if not row:
            return None
        return {**dict(row), "full_state": json.loads(row["full_state"])}

    def check_invariants(self, campus_id: str, conn) -> list:
        """Deep invariants check: no negative values, no over-capacity, no invalid state transitions.
        Returns list of error strings (empty = all invariants hold)."""
        errors = self.validate_state(campus_id, conn)

        # Additional invariants: no vehicle in closed/full lot
        for vrow in conn.execute("SELECT * FROM vehicle_state WHERE campus_id=?", (campus_id,)):
            if vrow["assigned_parking_lot_id"]:
                lot = conn.execute(
                    "SELECT usable_capacity FROM parking_lots WHERE campus_id=? AND parking_lot_id=?",
                    (campus_id, vrow["assigned_parking_lot_id"]),
                ).fetchone()
                if lot:
                    pstate = conn.execute(
                        "SELECT occupied_spaces FROM parking_lot_state WHERE campus_id=? AND parking_lot_id=?",
                        (campus_id, vrow["assigned_parking_lot_id"]),
                    ).fetchone()
                    if pstate and pstate["occupied_spaces"] >= lot["usable_capacity"]:
                        if vrow["state"] in ("PARKED",):
                            errors.append(
                                f"Vehicle {vrow['vehicle_id']} assigned to full lot {vrow['assigned_parking_lot_id']}"
                            )

        # No vehicle in two places at once
        seen_vids = set()
        for vrow in conn.execute("SELECT vehicle_id FROM vehicle_state WHERE campus_id=? AND state IN ('PARKED', 'SEARCHING')",
                                  (campus_id,)):
            if vrow["vehicle_id"] in seen_vids:
                errors.append(f"Vehicle {vrow['vehicle_id']} appears twice in active state")
            seen_vids.add(vrow["vehicle_id"])

        return errors

    def fork(self, campus_id: str, conn, fork_timestamp: str = None) -> dict:
        """Create a deep, independent copy of current state as a snapshot dict.
        Can later be restored to a new instance via restore_snapshot().
        Returns the full state dict (snapshot content)."""
        fork_timestamp = fork_timestamp or datetime.now(timezone.utc).isoformat()
        state = self.get_current_state(campus_id, conn)
        return {
            "campus_id": campus_id,
            "fork_timestamp": fork_timestamp,
            "full_state": state,
        }

    def restore_from_fork(self, campus_id: str, fork_dict: dict, conn):
        """Restore a fork (returned by fork()) into this campus's current state.
        The fork is independent: mutations here don't affect the original."""
        full_state = fork_dict["full_state"]

        # Clear current state
        for table in ("parking_lot_state", "gate_state", "road_state", "vehicle_state"):
            conn.execute(f"DELETE FROM {table} WHERE campus_id=?", (campus_id,))

        # Restore from fork's snapshot
        for p in full_state.get("parking", []):
            conn.execute(
                """INSERT INTO parking_lot_state (campus_id, parking_lot_id, occupied_spaces, available_spaces,
                     occupancy_percentage, predicted_occupancy, status, observation_timestamp,
                     ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, p["parking_lot_id"], p["occupied_spaces"], p["available_spaces"],
                 p["occupancy_percentage"], p.get("predicted_occupancy"), p["status"],
                 p["observation_timestamp"], p["ingestion_timestamp"], p["source"], p["provenance"]),
            )
        for g in full_state.get("gates", []):
            conn.execute(
                """INSERT INTO gate_state (campus_id, gate_id, current_queue_length, throughput_last_5min,
                     status, observation_timestamp, ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, g["gate_id"], g["current_queue_length"], g["throughput_last_5min"],
                 g["status"], g["observation_timestamp"], g["ingestion_timestamp"], g["source"], g["provenance"]),
            )
        for r in full_state.get("roads", []):
            conn.execute(
                """INSERT INTO road_state (campus_id, road_id, current_load, congestion_level,
                     status, observation_timestamp, ingestion_timestamp, source, provenance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, r["road_id"], r["current_load"], r["congestion_level"],
                 r["status"], r["observation_timestamp"], r["ingestion_timestamp"], r["source"], r["provenance"]),
            )
        for v in full_state.get("vehicles", []):
            conn.execute(
                """INSERT INTO vehicle_state (campus_id, vehicle_id, arrival_time, destination_id,
                     assigned_parking_lot_id, current_node_id, route, state, source, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (campus_id, v["vehicle_id"], v.get("arrival_time"), v.get("destination_id"),
                 v.get("assigned_parking_lot_id"), v.get("current_node_id"), v.get("route"),
                 v["state"], v["source"], v["timestamp"]),
            )
        conn.commit()
