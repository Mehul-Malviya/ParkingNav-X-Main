import json
import sys
from pathlib import Path

# Lets this test find the main ParkingNav_X folder
project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.routing.dijkstra import dijkstra


def load_graph():
    graph_path = project_folder / "data" / "mock" / "mock_graph.json"

    with open(graph_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_dijkstra():
    graph = load_graph()

    route, cost = dijkstra(graph, "Gate1", "ParkingB")

    assert route == ["Gate1", "RoadA", "RoadD", "ParkingB"]
    assert cost == 9


# This makes the normal VS Code Run button execute the test
if __name__ == "__main__":
    test_dijkstra()
    print("Test passed! ✅")