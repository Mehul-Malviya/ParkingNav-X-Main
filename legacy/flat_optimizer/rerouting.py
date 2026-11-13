from optimization.constraints.road_constraints import is_road_open
from optimization.routing.dijkstra import dijkstra


def reroute(graph, start, destination, blocked_nodes=None):
    if blocked_nodes is None:
        blocked_nodes = set()
    else:
        blocked_nodes = set(blocked_nodes)

    # Cannot route if the start or destination is blocked
    if not is_road_open(start, blocked_nodes):
        return [], float("inf")

    if not is_road_open(destination, blocked_nodes):
        return [], float("inf")

    available_graph = {}

    for node, neighbors in graph.items():
        if not is_road_open(node, blocked_nodes):
            continue

        available_graph[node] = {}

        for neighbor, weight in neighbors.items():
            if is_road_open(neighbor, blocked_nodes):
                available_graph[node][neighbor] = weight

    return dijkstra(available_graph, start, destination)