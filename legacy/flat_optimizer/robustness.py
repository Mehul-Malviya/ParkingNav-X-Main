def evaluate_rerouting_robustness(
    original_route,
    original_cost,
    rerouted_route,
    rerouted_cost
):
    if not rerouted_route:
        return {
            "route_available": False,
            "route_changed": True,
            "cost_change": None,
            "cost_change_percent": None
        }

    cost_change = rerouted_cost - original_cost
    cost_change_percent = (cost_change / original_cost) * 100

    return {
        "route_available": True,
        "route_changed": original_route != rerouted_route,
        "cost_change": cost_change,
        "cost_change_percent": round(cost_change_percent, 2)
    }