-- Initial schema for the Digital Twin + Simulation subsystem.
-- Never rewrite this file once applied; add a new numbered migration instead.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campuses (
    campus_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    active_configuration_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS gates (
    campus_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    capacity INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    metadata TEXT,
    configuration_version TEXT NOT NULL,
    PRIMARY KEY (campus_id, gate_id),
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id)
);

CREATE TABLE IF NOT EXISTS roads (
    campus_id TEXT NOT NULL,
    road_id TEXT NOT NULL,
    name TEXT NOT NULL,
    start_node_id TEXT NOT NULL,
    end_node_id TEXT NOT NULL,
    length_meters REAL NOT NULL,
    expected_travel_time_seconds REAL,
    is_walkable INTEGER NOT NULL DEFAULT 1,
    is_driveable INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    geometry TEXT NOT NULL,
    configuration_version TEXT NOT NULL,
    PRIMARY KEY (campus_id, road_id),
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id)
);

CREATE TABLE IF NOT EXISTS parking_lots (
    campus_id TEXT NOT NULL,
    parking_lot_id TEXT NOT NULL,
    name TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    boundary_polygon TEXT,
    zone TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    total_capacity INTEGER NOT NULL,
    usable_capacity INTEGER NOT NULL,
    reserved_capacity INTEGER NOT NULL DEFAULT 0,
    restricted_capacity INTEGER NOT NULL DEFAULT 0,
    temporarily_unavailable_capacity INTEGER NOT NULL DEFAULT 0,
    configuration_version TEXT NOT NULL,
    PRIMARY KEY (campus_id, parking_lot_id),
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id)
);

CREATE TABLE IF NOT EXISTS destinations (
    campus_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    department_names TEXT,
    searchable_aliases TEXT,
    nearest_gate_ids TEXT,
    nearest_parking_lot_ids TEXT,
    configuration_version TEXT NOT NULL,
    PRIMARY KEY (campus_id, destination_id),
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id)
);

CREATE TABLE IF NOT EXISTS events (
    campus_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    name TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    expected_demand_multiplier REAL NOT NULL DEFAULT 1.0,
    affected_zones TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    PRIMARY KEY (campus_id, event_id),
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id)
);

CREATE TABLE IF NOT EXISTS routes_graph_edges (
    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    from_node_id TEXT NOT NULL,
    to_node_id TEXT NOT NULL,
    road_id TEXT,
    weight_time_seconds REAL NOT NULL,
    weight_distance_meters REAL NOT NULL,
    is_walkable INTEGER NOT NULL DEFAULT 1,
    is_driveable INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (campus_id) REFERENCES campuses(campus_id),
    UNIQUE (campus_id, from_node_id, to_node_id)
);

CREATE TABLE IF NOT EXISTS parking_lot_state (
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
    PRIMARY KEY (campus_id, parking_lot_id)
);

CREATE TABLE IF NOT EXISTS gate_state (
    campus_id TEXT NOT NULL,
    gate_id TEXT NOT NULL,
    current_queue_length INTEGER NOT NULL DEFAULT 0,
    throughput_last_5min INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    observation_timestamp TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (campus_id, gate_id)
);

CREATE TABLE IF NOT EXISTS road_state (
    campus_id TEXT NOT NULL,
    road_id TEXT NOT NULL,
    current_load INTEGER NOT NULL DEFAULT 0,
    congestion_level TEXT NOT NULL DEFAULT 'free',
    status TEXT NOT NULL DEFAULT 'open',
    observation_timestamp TEXT NOT NULL,
    ingestion_timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL,
    PRIMARY KEY (campus_id, road_id)
);

CREATE TABLE IF NOT EXISTS vehicle_state (
    campus_id TEXT NOT NULL,
    vehicle_id TEXT NOT NULL,
    arrival_time TEXT,
    destination_id TEXT,
    assigned_parking_lot_id TEXT,
    current_node_id TEXT,
    route TEXT,
    state TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    PRIMARY KEY (campus_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS campus_state_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    campus_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    configuration_version TEXT,
    full_state TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id TEXT PRIMARY KEY,
    campus_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    strategy_name TEXT NOT NULL,
    configuration_version TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running'
);
