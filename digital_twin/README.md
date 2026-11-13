# digital_twin/

The active Member 1 subsystem: Campus Configuration â†’ Campus Graph â†’
Digital Twin State â†’ Simulation â†’ Scenarios, plus the FastAPI app and
CLI tools that expose all of it. Full writeup:
[docs/MEMBER1_SUBSYSTEM_REPORT.md](../docs/MEMBER1_SUBSYSTEM_REPORT.md).

| File/folder | What it is |
|---|---|
| `db.py` | SQLite connection + migration runner (see `../migrations/`) |
| `models.py` | Shared enums: `Provenance`, `EntityStatus`, `FreshnessState`, etc. |
| `config_loader.py` | Loads/validates a campus YAML (`../configs/campus/*.yaml`) into the DB |
| `gps_survey_import.py` | Converts a GPX+CSV survey into that same YAML format |
| `graph_service.py` | Builds a `networkx` graph per campus â€” structure only, no pathfinding |
| `twin_service.py` | `DigitalTwinService` â€” the live campus state: parking/gate/road/vehicle, snapshots, history |
| `scheduler.py` | `SnapshotScheduler` â€” periodic `snapshot_now()` calls |
| `simulation/` | The deterministic simulation engine, scenario loader/validator, the `AllocationStrategy` interface |
| `api/app.py` | FastAPI app exposing all of the above |
| `cli/` | `run.py` (simulation), `validate_scenario.py` |

## Quick start

See the commands in the top-level [README.md](../README.md#common-tasks).
Run them from the repo root.
