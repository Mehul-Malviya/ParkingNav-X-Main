"""
Part 2: Campus Graph. Builds the routable network structure from Part 1's
data using networkx. Deliberately does NOT implement shortest-path/route-
finding -- that's the Navigation module's job, built on top of what's
exposed here (the graph object itself, or its GeoJSON/JSON export).
"""

import json

import networkx as nx


class CampusGraphService:
    """One graph instance per campus_id, cached until refresh_graph is
    called. Two campuses never share nodes/edges, even on an ID collision,
    because each graph is keyed and built independently."""

    def __init__(self):
        self._cache = {}

    def build_graph(self, campus_id: str, conn) -> nx.DiGraph:
        if campus_id in self._cache:
            return self._cache[campus_id]
        return self.refresh_graph(campus_id, conn)

    def refresh_graph(self, campus_id: str, conn) -> nx.DiGraph:
        graph = nx.DiGraph()  # directed: road from→to is one-way unless both directions in DB

        for row in conn.execute("SELECT * FROM gates WHERE campus_id=?", (campus_id,)):
            graph.add_node(row["gate_id"], type="gate", latitude=row["latitude"],
                            longitude=row["longitude"], status=row["status"])

        for row in conn.execute("SELECT * FROM parking_lots WHERE campus_id=?", (campus_id,)):
            graph.add_node(row["parking_lot_id"], type="parking_lot", latitude=row["latitude"],
                            longitude=row["longitude"], status=row["status"])

        for row in conn.execute("SELECT * FROM destinations WHERE campus_id=?", (campus_id,)):
            graph.add_node(row["destination_id"], type="destination", latitude=row["latitude"],
                            longitude=row["longitude"], status="open")

        # Road polylines are the source of truth for where a route is drawn.
        # Each is stored start->end; an edge travelling end->start gets it reversed.
        roads = {}
        for row in conn.execute(
            "SELECT road_id, start_node_id, end_node_id, geometry FROM roads WHERE campus_id=?",
            (campus_id,),
        ):
            try:
                points = json.loads(row["geometry"]) if row["geometry"] else []
            except (TypeError, ValueError):
                points = []
            roads[row["road_id"]] = (row["start_node_id"], row["end_node_id"], points)

        for row in conn.execute("SELECT * FROM routes_graph_edges WHERE campus_id=?", (campus_id,)):
            start_id, _, points = roads.get(row["road_id"], (None, None, []))
            if points and row["from_node_id"] != start_id:
                points = list(reversed(points))
            graph.add_edge(
                row["from_node_id"], row["to_node_id"],
                road_id=row["road_id"],
                weight_time_seconds=row["weight_time_seconds"],
                weight_distance_meters=row["weight_distance_meters"],
                is_walkable=bool(row["is_walkable"]),
                is_driveable=bool(row["is_driveable"]),
                status=row["status"],
                geometry=points,
            )

        self._cache[campus_id] = graph
        return graph

    def get_neighbors(self, graph: nx.DiGraph, node_id: str) -> list:
        return list(graph.successors(node_id))

    def get_node(self, graph: nx.DiGraph, node_id: str) -> dict:
        return dict(graph.nodes[node_id])

    def get_edge(self, graph: nx.DiGraph, from_id: str, to_id: str) -> dict:
        return dict(graph.edges[from_id, to_id])

    def is_connected(self, graph: nx.Graph, node_a: str, node_b: str) -> bool:
        """Structural reachability only -- not a path, not a distance."""
        if node_a not in graph or node_b not in graph:
            return False
        return nx.has_path(graph, node_a, node_b)

    def get_graph_bounds(self, graph: nx.Graph) -> dict:
        lats = [d["latitude"] for _, d in graph.nodes(data=True) if d.get("latitude") is not None]
        lngs = [d["longitude"] for _, d in graph.nodes(data=True) if d.get("longitude") is not None]
        if not lats:
            return {"min_lat": None, "max_lat": None, "min_lng": None, "max_lng": None}
        return {"min_lat": min(lats), "max_lat": max(lats), "min_lng": min(lngs), "max_lng": max(lngs)}

    def to_json(self, graph: nx.Graph) -> dict:
        """Documented JSON shape: {nodes: [...], edges: [...]}. Navigation
        can consume this directly without hitting the DB again."""
        return {
            "nodes": [
                {"node_id": n, **d} for n, d in graph.nodes(data=True)
            ],
            "edges": [
                {"from_node_id": u, "to_node_id": v, **d} for u, v, d in graph.edges(data=True)
            ],
        }

    def to_geojson(self, graph: nx.Graph) -> dict:
        features = []
        for node_id, d in graph.nodes(data=True):
            if d.get("latitude") is None:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [d["longitude"], d["latitude"]]},
                "properties": {"node_id": node_id, "type": d.get("type"), "status": d.get("status")},
            })
        return {"type": "FeatureCollection", "features": features}
