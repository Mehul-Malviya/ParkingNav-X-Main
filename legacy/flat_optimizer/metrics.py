def calculate_improvement(baseline_cost, optimized_cost):
    if baseline_cost <= 0:
        raise ValueError("Baseline cost must be greater than 0.")

    absolute_improvement = baseline_cost - optimized_cost
    percentage_improvement = (
        absolute_improvement / baseline_cost
    ) * 100

    return {
        "absolute_improvement": absolute_improvement,
        "percentage_improvement": percentage_improvement
    }