import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.optimizer.parking_optimizer import find_best_parking


def load_json(filename):
    file_path = project_folder / "data" / "mock" / filename

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_parking_optimizer():
    graph = load_json("mock_graph.json")
    predictions = load_json("mock_predictions.json")
    parking_data = load_json("mock_parking.json")

    best_option = find_best_parking(
        graph,
        predictions,
        parking_data,
        "Gate1"
    )

    assert best_option["parking"] == "ParkingA"
    assert best_option["route"] == [
        "Gate1",
        "RoadA",
        "RoadC",
        "ParkingA"
    ]
    assert best_option["total_cost"] == 15.0


def test_closed_gate_returns_no_recommendation():
    graph = load_json("mock_graph.json")
    predictions = load_json("mock_predictions.json")
    parking_data = load_json("mock_parking.json")

    best_option = find_best_parking(
        graph,
        predictions,
        parking_data,
        "Gate1",
        closed_gates=["Gate1"]
    )

    assert best_option is None


if __name__ == "__main__":
    test_parking_optimizer()
    test_closed_gate_returns_no_recommendation()
    print("Parking optimizer tests passed! ✅")