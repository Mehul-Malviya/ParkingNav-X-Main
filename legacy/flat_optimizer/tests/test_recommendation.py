import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.optimizer.parking_optimizer import find_best_parking
from optimization.recommendation.recommendation import create_recommendation


def load_json(filename):
    file_path = project_folder / "data" / "mock" / filename

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_recommendation():
    graph = load_json("mock_graph.json")
    predictions = load_json("mock_predictions.json")
    parking_data = load_json("mock_parking.json")

    best_option = find_best_parking(
        graph,
        predictions,
        parking_data,
        "Gate1"
    )

    recommendation = create_recommendation(best_option)

    assert "Recommended parking: ParkingA" in recommendation
    assert "Gate1 → RoadA → RoadC → ParkingA" in recommendation


if __name__ == "__main__":
    test_recommendation()
    print("Recommendation test passed! ✅")