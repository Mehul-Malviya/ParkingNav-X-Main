from legacy.flat_optimizer.parking_constraints import is_parking_available
from legacy.flat_optimizer.dijkstra import dijkstra



def nearest_available_parking(graph, parking_data, start):
    nearest_parking = None
    lowest_cost = float("inf")

    for parking_name, details in parking_data.items():
        if not is_parking_available(details):
            continue

        route, route_cost = dijkstra(graph, start, parking_name)

        if route and route_cost < lowest_cost:
            nearest_parking = parking_name
            lowest_cost = route_cost

    return nearest_parking