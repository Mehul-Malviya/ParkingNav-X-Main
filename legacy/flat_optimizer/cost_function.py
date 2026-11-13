from optimization.objectives.weights import (
    DISTANCE_WEIGHT,
    CONGESTION_WEIGHT,
    OVERFLOW_WEIGHT,
)


def calculate_total_cost(route_cost, congestion_risk, overflow_risk):
    total_cost = (
        route_cost * DISTANCE_WEIGHT
        + congestion_risk * CONGESTION_WEIGHT
        + overflow_risk * OVERFLOW_WEIGHT
    )

    return total_cost