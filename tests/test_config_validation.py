"""
Config Validator: Comprehensive test suite for all invalid configurations.
Tests Section 19 Definition of Done item: "Validator rejects all invalid configs with clear messages"
"""

from pathlib import Path

import pytest

from digital_twin.config_loader import CampusConfigError, load_campus_config
from digital_twin.db import apply_migrations, get_connection


class TestConfigValidation:
    """Test that invalid configs are rejected with clear error messages."""

    @pytest.fixture
    def fresh_db(self):
        """Create fresh in-memory database."""
        conn = get_connection(':memory:')
        apply_migrations(conn)
        return conn

    def test_valid_sample_config_loads(self, fresh_db):
        """Baseline: valid config loads without error."""
        load_campus_config(Path('configs/campus/sample.yaml'), fresh_db)
        cursor = fresh_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM campuses")
        assert cursor.fetchone()[0] == 1

    def test_valid_vitap_config_loads(self, fresh_db):
        """Baseline: real VIT-AP config loads."""
        load_campus_config(Path('configs/campus/vitap.yaml'), fresh_db)
        cursor = fresh_db.cursor()
        cursor.execute("SELECT COUNT(*) FROM campuses")
        assert cursor.fetchone()[0] == 1

    def test_duplicate_gate_ids_rejected(self, fresh_db, tmp_path):
        """Error: Two gates with same ID."""
        config = """
campus:
  id: test_dup_gates
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
  - {id: G1, name: Gate 2, node: n_g2, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_gates.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="duplicate.*gate.*id"):
            load_campus_config(config_file, fresh_db)

    def test_duplicate_lot_ids_rejected(self, fresh_db, tmp_path):
        """Error: Two lots with same ID."""
        config = """
campus:
  id: test_dup_lots
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
  - {id: LA, name: Lot B, node: n_lb, capacity: 100, reserved: {accessible: 2, staff: 10},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_lots.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="duplicate.*lot.*id"):
            load_campus_config(config_file, fresh_db)

    def test_road_missing_from_node_rejected(self, fresh_db, tmp_path):
        """Error: Road references a node that doesn't exist."""
        config = """
campus:
  id: test_bad_road
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_missing, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_road_from.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="missing.*node|undefined.*node"):
            load_campus_config(config_file, fresh_db)

    def test_negative_capacity_rejected(self, fresh_db, tmp_path):
        """Error: Lot with capacity â‰¤ 0."""
        config = """
campus:
  id: test_bad_capacity
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: -50, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_capacity.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="capacity.*positive|must be > 0"):
            load_campus_config(config_file, fresh_db)

    def test_reserved_exceeds_capacity_rejected(self, fresh_db, tmp_path):
        """Error: Reserved spaces > total capacity."""
        config = """
campus:
  id: test_reserved_overflow
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 100, reserved: {accessible: 50, staff: 60},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_reserved.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="reserved.*exceed|sum.*reserved.*capacity"):
            load_campus_config(config_file, fresh_db)

    def test_zero_road_length_rejected(self, fresh_db, tmp_path):
        """Error: Road with length = 0."""
        config = """
campus:
  id: test_zero_length
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 0, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_length.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="length.*positive|length.*> 0"):
            load_campus_config(config_file, fresh_db)

    def test_zero_speed_rejected(self, fresh_db, tmp_path):
        """Error: Road with zero free speed."""
        config = """
campus:
  id: test_zero_speed
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 0,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_speed.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="speed.*positive|speed.*> 0"):
            load_campus_config(config_file, fresh_db)

    def test_lot_unreachable_from_gate_rejected(self, fresh_db, tmp_path):
        """Error: A lot with no road path from any gate (disconnected)."""
        config = """
campus:
  id: test_disconnected
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
  - {id: LB, name: Lot B, node: n_lb, capacity: 100, reserved: {accessible: 2, staff: 10},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA, LB], walk_time_min: {LA: 2, LB: 5}}
"""
        config_file = tmp_path / "bad_unreachable.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="unreachable|not reachable|disconnected"):
            load_campus_config(config_file, fresh_db)

    def test_missing_zone_for_lot_rejected(self, fresh_db, tmp_path):
        """Error: Lot references a zone that doesn't exist."""
        config = """
campus:
  id: test_bad_zone
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: missing_zone, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_lot_zone.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="zone.*not found|undefined.*zone"):
            load_campus_config(config_file, fresh_db)

    def test_event_multiplier_zero_rejected(self, fresh_db, tmp_path):
        """Error: Event with multiplier = 0 (no one arrives)."""
        config = """
campus:
  id: test_bad_event
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
event_types:
  - {id: bad_event, demand_multiplier: 0, affected_zones: [academic]}
"""
        config_file = tmp_path / "bad_event.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="multiplier.*positive|multiplier.*> 0"):
            load_campus_config(config_file, fresh_db)

    def test_empty_gates_list_rejected(self, fresh_db, tmp_path):
        """Error: No gates defined."""
        config = """
campus:
  id: test_no_gates
  name: Test
gates: []
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "no_gates.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="at least one gate|gates.*empty"):
            load_campus_config(config_file, fresh_db)

    def test_empty_lots_list_rejected(self, fresh_db, tmp_path):
        """Error: No lots defined."""
        config = """
campus:
  id: test_no_lots
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: open}
lots: []
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [], walk_time_min: {}}
"""
        config_file = tmp_path / "no_lots.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="at least one lot|lots.*empty"):
            load_campus_config(config_file, fresh_db)

    def test_invalid_status_rejected(self, fresh_db, tmp_path):
        """Error: Invalid status value (not 'open' or 'closed')."""
        config = """
campus:
  id: test_bad_status
  name: Test
gates:
  - {id: G1, name: Gate 1, node: n_g1, service_rate_veh_per_min: 6, lanes: 2, status: maybe_open}
lots:
  - {id: LA, name: Lot A, node: n_la, capacity: 120, reserved: {accessible: 4, staff: 20},
     zone: academic, search_base_min: 0.5, status: open}
roads:
  - {id: R1, from: n_g1, to: n_la, length_m: 100, free_speed_kmph: 20,
     capacity_veh_per_hr: 600, bidirectional: false, status: open}
zones:
  - {id: academic, preferred_lots: [LA], walk_time_min: {LA: 2}}
"""
        config_file = tmp_path / "bad_status.yaml"
        config_file.write_text(config)
        with pytest.raises(CampusConfigError, match="status.*open|closed|invalid.*status"):
            load_campus_config(config_file, fresh_db)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
