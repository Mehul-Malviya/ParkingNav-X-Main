from pathlib import Path

import pytest

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.graph_service import CampusGraphService

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = PROJECT_ROOT / "configs" / "campus"


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    apply_migrations(c)
    load_campus_config(CONFIGS / "sample.yaml", c)
    load_campus_config(CONFIGS / "vitap.yaml", c)
    yield c
    c.close()


def test_graph_reflects_sample_campus(conn):
    service = CampusGraphService()
    graph = service.build_graph("sample", conn)
    assert graph.number_of_nodes() == 4   # 1 gate + 2 lots + 1 destination
    assert graph.number_of_edges() == 3


def test_two_campuses_are_fully_isolated(conn):
    service = CampusGraphService()
    sample_graph = service.build_graph("sample", conn)
    vitap_graph = service.build_graph("vitap", conn)

    assert "sample-gate-1" in sample_graph
    assert "sample-gate-1" not in vitap_graph
    assert "vitap-gate-main" in vitap_graph
    assert "vitap-gate-main" not in sample_graph


def test_shared_node_id_does_not_create_false_cross_campus_edge(conn):
    # Even if two campuses hypothetically had a colliding node ID, the two
    # graph objects are entirely separate structures with no shared edges.
    service = CampusGraphService()
    sample_graph = service.build_graph("sample", conn)
    vitap_graph = service.build_graph("vitap", conn)
    assert sample_graph is not vitap_graph
    assert set(sample_graph.edges()).isdisjoint(set(vitap_graph.edges()))


def test_refresh_graph_picks_up_new_road_without_restart(conn):
    service = CampusGraphService()
    graph_before = service.build_graph("sample", conn)
    assert graph_before.number_of_edges() == 3

    conn.execute(
        """INSERT INTO routes_graph_edges (campus_id, from_node_id, to_node_id, road_id,
             weight_time_seconds, weight_distance_meters, is_walkable, is_driveable, status)
           VALUES ('sample', 'sample-lot-2', 'sample-dest-1', 'sample-road-new', 30, 40, 1, 0, 'open')"""
    )
    conn.commit()

    graph_after = service.refresh_graph("sample", conn)
    assert graph_after.number_of_edges() == 4
    assert service.is_connected(graph_after, "sample-lot-2", "sample-dest-1")


def test_is_connected_identifies_isolated_node_as_unreachable(conn):
    service = CampusGraphService()
    graph = service.build_graph("sample", conn)
    graph.add_node("isolated-test-node", type="destination", latitude=99.0, longitude=99.0, status="open")
    assert service.is_connected(graph, "sample-gate-1", "isolated-test-node") is False


def test_get_graph_bounds(conn):
    service = CampusGraphService()
    graph = service.build_graph("sample", conn)
    bounds = service.get_graph_bounds(graph)
    assert bounds["min_lat"] <= 10.0000 <= bounds["max_lat"]


def test_get_neighbors_and_get_node(conn):
    service = CampusGraphService()
    graph = service.build_graph("sample", conn)
    assert "sample-lot-1" in service.get_neighbors(graph, "sample-gate-1")
    node = service.get_node(graph, "sample-gate-1")
    assert node["type"] == "gate"


if __name__ == "__main__":
    print("Run with pytest: python -m pytest test_part2_campus_graph.py -v")
