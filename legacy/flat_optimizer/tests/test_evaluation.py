import sys
from pathlib import Path

project_folder = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_folder))

from optimization.evaluation.comparison import compare_costs
from optimization.evaluation.metrics import calculate_improvement
from optimization.evaluation.robustness import evaluate_rerouting_robustness


def test_calculate_improvement():
    result = calculate_improvement(
        baseline_cost=20,
        optimized_cost=15
    )

    assert result["absolute_improvement"] == 5
    assert result["percentage_improvement"] == 25.0


def test_compare_costs():
    comparison = compare_costs(
        baseline_cost=20,
        optimized_cost=15
    )

    assert comparison["baseline_cost"] == 20
    assert comparison["optimized_cost"] == 15
    assert comparison["absolute_improvement"] == 5
    assert comparison["percentage_improvement"] == 25.0


def test_rerouting_robustness():
    original_route = [
        "Gate1",
        "RoadA",
        "RoadD",
        "ParkingB"
    ]

    rerouted_route = [
        "Gate1",
        "RoadA",
        "RoadC",
        "ParkingB"
    ]

    result = evaluate_rerouting_robustness(
        original_route,
        original_cost=9,
        rerouted_route=rerouted_route,
        rerouted_cost=11
    )

    assert result["route_available"] is True
    assert result["route_changed"] is True
    assert result["cost_change"] == 2
    assert result["cost_change_percent"] == 22.22


if __name__ == "__main__":
    test_calculate_improvement()
    test_compare_costs()
    test_rerouting_robustness()
    print("Evaluation tests passed! ✅")