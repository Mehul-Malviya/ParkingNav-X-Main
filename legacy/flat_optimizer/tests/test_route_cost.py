import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.routing.route_cost import calculate_route_cost


def load_graph():
    graph_path = project_folder / "data" / "mock" / "mock_graph.json"

    with open(graph_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_route_cost():
    graph = load_graph()

    route = ["Gate1", "RoadA", "RoadD", "ParkingB"]
    cost = calculate_route_cost(graph, route)

    assert cost == 9


if __name__ == "__main__":
    test_route_cost()
    print("Route-cost test passed! ✅")