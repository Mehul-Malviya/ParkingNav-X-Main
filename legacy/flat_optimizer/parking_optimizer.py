from optimization.constraints.gate_constraints import is_gate_open
from optimization.constraints.parking_constraints import is_parking_available
from optimization.objectives.cost_function import calculate_total_cost
from optimization.risk.congestion_risk import calculate_congestion_risk
from optimization.risk.overflow_risk import calculate_overflow_risk
from optimization.routing.dijkstra import dijkstra


def get_route_congestion_risk(route, predictions):
    congestion_levels = []

    for node in route:
        if node in predictions:
            congestion_levels.append(
                calculate_congestion_risk(predictions[node])
            )

    if not congestion_levels:
        return 0

    return sum(congestion_levels) / len(congestion_levels)


def find_best_parking(
    graph,
    predictions,
    parking_data,
    start,
    closed_gates=None
):
    if closed_gates is None:
        closed_gates = []

    # Do not optimize from a closed gate
    if not is_gate_open(start, closed_gates):
        return None

    best_option = None

    for parking_name, details in parking_data.items():
        occupied = details["occupied"]
        capacity = details["capacity"]

        if not is_parking_available(details):
            continue

        route, route_cost = dijkstra(graph, start, parking_name)

        if not route:
            continue

        congestion_risk = get_route_congestion_risk(route, predictions)

        overflow_risk = calculate_overflow_risk(
            occupied,
            capacity
        )

        total_cost = calculate_total_cost(
            route_cost,
            congestion_risk,
            overflow_risk
        )

        option = {
            "parking": parking_name,
            "route": route,
            "route_cost": route_cost,
            "congestion_risk": congestion_risk,
            "overflow_risk": overflow_risk,
            "total_cost": total_cost
        }

        if best_option is None or option["total_cost"] < best_option["total_cost"]:
            best_option = option

    return best_option