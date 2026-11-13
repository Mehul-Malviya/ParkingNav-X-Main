#!/usr/bin/env python3
"""
Export a campus graph as PNG diagram.

Usage:
  python scripts/export_campus_graph_png.py --campus <campus_id> --output <path.png>

Reuses existing graph_service to build the routable network, then
visualizes it with matplotlib/networkx for inclusion in reports.
"""

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import networkx as nx
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from digital_twin.config_loader import load_campus_config
from digital_twin.db import apply_migrations, get_connection
from digital_twin.graph_service import CampusGraphService

PROJECT_ROOT = Path(__file__).parent.parent


def export_campus_graph_png(campus_id: str, config_path: str, output_path: str):
    """Load campus config, build graph, export as PNG."""
    db_path = PROJECT_ROOT / "documentation" / "database" / "digital_twin.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(db_path)
    apply_migrations(conn)

    # Load config into DB
    loaded_id = load_campus_config(config_path, conn)
    assert loaded_id == campus_id, f"Campus ID mismatch: {loaded_id} vs {campus_id}"

    # Build graph
    graph_svc = CampusGraphService()
    graph = graph_svc.build_graph(campus_id, conn)

    # Layout based on real geographical coordinates (longitude = x, latitude = y)
    pos = {}
    for node, data in graph.nodes(data=True):
        if data.get("longitude") is not None and data.get("latitude") is not None:
            pos[node] = (data["longitude"], data["latitude"])
        else:
            pos[node] = (0, 0)

    # Colors by node type
    node_colors = []
    for node in graph.nodes():
        node_type = graph.nodes[node].get("type", "unknown")
        if node_type == "gate":
            node_colors.append("#e74c3c")  # Modern red
        elif node_type == "parking_lot":
            node_colors.append("#2980b9")  # Modern blue
        elif node_type == "destination":
            node_colors.append("#27ae60")  # Modern green
        else:
            node_colors.append("gray")

    # Query human-readable names for all nodes
    labels = {}
    for row in conn.execute("SELECT gate_id, name FROM gates WHERE campus_id=?", (campus_id,)):
        labels[row["gate_id"]] = row["name"]
    for row in conn.execute("SELECT parking_lot_id, name FROM parking_lots WHERE campus_id=?", (campus_id,)):
        labels[row["parking_lot_id"]] = row["name"]
    for row in conn.execute("SELECT destination_id, name FROM destinations WHERE campus_id=?", (campus_id,)):
        labels[row["destination_id"]] = row["name"]

    # Fallback to node_id if name missing
    for node in graph.nodes():
        if node not in labels:
            labels[node] = node

    # Query road geometries from DB
    road_geometries = []
    for row in conn.execute("SELECT geometry FROM roads WHERE campus_id=?", (campus_id,)):
        try:
            geom = yaml.safe_load(row["geometry"])
            if isinstance(geom, list):
                coords = [(pt["lng"], pt["lat"]) for pt in geom if "lng" in pt and "lat" in pt]
                if len(coords) >= 2:
                    road_geometries.append(coords)
        except Exception:
            pass

    # Draw
    fig, ax = plt.subplots(figsize=(16, 13))

    # Draw actual curved/segment road geometries from OpenStreetMap geometry array
    for coords in road_geometries:
        xs, ys = zip(*coords)
        ax.plot(xs, ys, color="#95a5a6", linewidth=2.5, alpha=0.7, zorder=1)

    # Draw topological straight graph edges
    nx.draw_networkx_edges(graph, pos, edge_color="#7f8c8d", width=1.2, ax=ax, alpha=0.5)

    # Draw nodes
    nx.draw_networkx_nodes(
        graph, pos, node_color=node_colors, node_size=1200, ax=ax, alpha=0.95
    )

    # Draw labels with high-contrast white background box
    for node, (x, y) in pos.items():
        name = labels.get(node, node)
        ax.text(
            x, y + 0.00025, name,
            fontsize=9.5, fontweight="bold", ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#34495e", alpha=0.88, linewidth=1)
        )

    ax.set_title("VIT-AP Geographic Campus Graph & Building Routing Map", fontsize=18, fontweight="bold", pad=20)
    ax.axis("off")



    # Legend
    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor="red", label="Gates (entry/exit)"),
        Patch(facecolor="blue", label="Parking Lots"),
        Patch(facecolor="green", label="Destinations (buildings)"),
    ]
    ax.legend(handles=legend_elements, loc="upper left")

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"OK: Campus graph exported: {output_path}")
    plt.close(fig)

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Export campus graph as PNG diagram"
    )
    parser.add_argument(
        "--campus", required=True, help="Campus ID (e.g., vitap, toy_small)"
    )
    parser.add_argument(
        "--config", required=True, help="Path to campus YAML config file"
    )
    parser.add_argument(
        "--output", required=True, help="Output PNG file path"
    )

    args = parser.parse_args()
    export_campus_graph_png(args.campus, args.config, args.output)
