import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.objectives.cost_function import calculate_total_cost
from optimization.risk.congestion_risk import calculate_congestion_risk
from optimization.risk.overflow_risk import calculate_overflow_risk
from optimization.routing.route_cost import calculate_route_cost


def load_json(filename):
    file_path = project_folder / "data" / "mock" / filename

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_total_cost():
    graph = load_json("mock_graph.json")
    predictions = load_json("mock_predictions.json")
    parking_data = load_json("mock_parking.json")

    route = ["Gate1", "RoadA", "RoadD", "ParkingB"]

    route_cost = calculate_route_cost(graph, route)
    congestion_risk = calculate_congestion_risk(predictions["RoadD"])
    overflow_risk = calculate_overflow_risk(
        parking_data["ParkingB"]["occupied"],
        parking_data["ParkingB"]["capacity"]
    )

    total_cost = calculate_total_cost(
        route_cost,
        congestion_risk,
        overflow_risk
    )

    assert total_cost == 22.5


if __name__ == "__main__":
    test_total_cost()
    print("Objective test passed! ✅")