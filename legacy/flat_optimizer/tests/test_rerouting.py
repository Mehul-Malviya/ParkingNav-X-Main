import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.routing.rerouting import reroute


def load_graph():
    graph_path = project_folder / "data" / "mock" / "mock_graph.json"

    with open(graph_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_rerouting():
    graph = load_graph()

    # RoadD is blocked, so the app must use a different route
    route, cost = reroute(
        graph,
        "Gate1",
        "ParkingB",
        blocked_nodes=["RoadD"]
    )

    assert route == ["Gate1", "RoadA", "RoadC", "ParkingB"]
    assert cost == 11


if __name__ == "__main__":
    test_rerouting()
    print("Rerouting test passed! ✅")