import json
import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.baselines.first_available import first_available_parking
from optimization.baselines.nearest_available import nearest_available_parking


def load_json(filename):
    file_path = project_folder / "data" / "mock" / filename

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)


def test_first_available_parking():
    parking_data = load_json("mock_parking.json")

    selected_parking = first_available_parking(parking_data)

    assert selected_parking == "ParkingA"


def test_nearest_available_parking():
    graph = load_json("mock_graph.json")
    parking_data = load_json("mock_parking.json")

    selected_parking = nearest_available_parking(
        graph,
        parking_data,
        "Gate1"
    )

    assert selected_parking == "ParkingA"


if __name__ == "__main__":
    test_first_available_parking()
    test_nearest_available_parking()
    print("Baseline tests passed! ✅")