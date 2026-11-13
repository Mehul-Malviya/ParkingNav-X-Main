import json
from pathlib import Path

from optimization.optimizer.parking_optimizer import find_best_parking
from optimization.recommendation.recommendation import create_recommendation


project_folder = Path(__file__).resolve().parent


def load_json(filename):
    file_path = project_folder / "data" / "mock" / filename

    with open(file_path, "r", encoding="utf-8") as file:
        return json.load(file)

def main():
    graph = load_json("mock_graph.json")
    predictions = load_json("mock_predictions.json")
    parking_data = load_json("mock_parking.json")

    start_gate = "Gate1"

    best_option = find_best_parking(
        graph,
        predictions,
        parking_data,
        start_gate
    )

    recommendation = create_recommendation(best_option)

    print("\n--- Parking Nav X ---")
    print(recommendation)


if __name__ == "__main__":
    main()