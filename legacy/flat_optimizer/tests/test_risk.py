import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.risk.congestion_risk import calculate_congestion_risk
from optimization.risk.overflow_risk import calculate_overflow_risk


def load_predictions():
    predictions_path = project_folder / "data" / "mock" / "mock_predictions.json"

    with open(predictions_path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_parking_data():
    parking_path = project_folder / "data" / "mock" / "mock_parking.json"

    with open(parking_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_congestion_risk():
    predictions = load_predictions()

    road_d_risk = calculate_congestion_risk(predictions["RoadD"])

    assert road_d_risk == 0.9


def test_overflow_risk():
    parking_data = load_parking_data()

    parking_b_risk = calculate_overflow_risk(
        parking_data["ParkingB"]["occupied"],
        parking_data["ParkingB"]["capacity"]
    )

    assert parking_b_risk == 0.9


if __name__ == "__main__":
    test_congestion_risk()
    test_overflow_risk()
    print("Risk tests passed! ✅")