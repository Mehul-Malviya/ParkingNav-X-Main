from optimization.evaluation.metrics import calculate_improvement


def compare_costs(baseline_cost, optimized_cost):
    improvement = calculate_improvement(
        baseline_cost,
        optimized_cost
    )

    return {
        "baseline_cost": baseline_cost,
        "optimized_cost": optimized_cost,
        "absolute_improvement": improvement["absolute_improvement"],
        "percentage_improvement": improvement["percentage_improvement"]
    }