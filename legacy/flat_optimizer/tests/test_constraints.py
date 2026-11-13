import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.constraints.gate_constraints import is_gate_open
from optimization.constraints.parking_constraints import is_parking_available
from optimization.constraints.road_constraints import is_road_open


def load_parking_data():
    parking_path = project_folder / "data" / "mock" / "mock_parking.json"

    with open(parking_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_parking_constraints():
    parking_data = load_parking_data()

    assert is_parking_available(parking_data["ParkingA"]) is True
    assert is_parking_available(parking_data["ParkingB"]) is True

    full_parking = {
        "capacity": 50,
        "occupied": 50
    }

    assert is_parking_available(full_parking) is False


def test_road_constraints():
    blocked_roads = ["RoadD"]

    assert is_road_open("RoadA", blocked_roads) is True
    assert is_road_open("RoadD", blocked_roads) is False


def test_gate_constraints():
    closed_gates = ["Gate2"]

    assert is_gate_open("Gate1", closed_gates) is True
    assert is_gate_open("Gate2", closed_gates) is False


if __name__ == "__main__":
    test_parking_constraints()
    test_road_constraints()
    test_gate_constraints()
    print("Constraint tests passed! ✅")