def dijkstra(graph, start, destination):
    distances = {}
    previous = {}
    visited = set()

    for node in graph:
        distances[node] = float("inf")

    distances[start] = 0

    while len(visited) < len(graph):
        current = None
        current_distance = float("inf")

        # Choose the closest unvisited node
        for node in graph:
            if node not in visited and distances[node] < current_distance:
                current = node
                current_distance = distances[node]

        # No reachable nodes remain
        if current is None:
            break

        # The shortest route to the destination is now known
        if current == destination:
            break

        visited.add(current)

        # Update the distances of neighboring nodes
        for neighbor, weight in graph[current].items():
            if neighbor in visited:
                continue

            new_distance = distances[current] + weight

            if new_distance < distances[neighbor]:
                distances[neighbor] = new_distance
                previous[neighbor] = current

    # No route exists
    if distances[destination] == float("inf"):
        return [], float("inf")

    # Build the route backward, from destination to start
    route = []
    current = destination

    while current is not None:
        route.append(current)

        if current == start:
            break

        current = previous.get(current)

    route.reverse()

    return route, distances[destination]