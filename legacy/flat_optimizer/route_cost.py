def calculate_route_cost(graph, route):
    total_cost = 0

    # A route with fewer than two points has no travel cost
    if len(route) < 2:
        return total_cost

    for index in range(len(route) - 1):
        current_node = route[index]
        next_node = route[index + 1]

        # Add the cost of moving from one node to the next
        total_cost += graph[current_node][next_node]

    return total_cost