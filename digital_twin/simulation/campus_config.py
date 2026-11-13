"""
Part 1 (M1): Campus Configuration — Pydantic models, loader, DiGraph builder, plotter.

Usage:
    from digital_twin.simulation.campus_config import load_campus, build_digraph, plot_campus
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Literal

import networkx as nx
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


# ── Pydantic models ──────────────────────────────────────────────────────────

class NodeConfig(BaseModel):
    id: str
    type: Literal["gate", "junction", "lot_entrance"]
    lat: float
    lon: float
    name: str = ""


class GateConfig(BaseModel):
    id: str
    node: str
    service_rate_vph: float
    lanes: int
    status: Literal["open", "closed"] = "open"


class RoadConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    length_m: float
    free_speed_kmph: float
    capacity_vph: float
    status: Literal["open", "closed"] = "open"

    @property
    def travel_time_sec(self) -> float:
        return (self.length_m / 1000.0) / self.free_speed_kmph * 3600.0


class ReservedConfig(BaseModel):
    accessible: int = 0
    staff: int = 0

    @property
    def total(self) -> int:
        return self.accessible + self.staff


class ParkingLotConfig(BaseModel):
    id: str
    entrance_node: str
    capacity: int
    reserved: ReservedConfig
    zone: str
    status: Literal["open", "closed"] = "open"
    internal_search_sec_per_10pct: float = 6.0


class ZoneConfig(BaseModel):
    id: str
    name: str
    nearest_nodes: List[str]
    walk_time_to_lot_sec: Dict[str, float]


class CampusConfig(BaseModel):
    id: str
    name: str
    time_step_sec: int = 10
    nodes: List[NodeConfig]
    gates: List[GateConfig]
    roads: List[RoadConfig]
    parking_lots: List[ParkingLotConfig]
    zones: List[ZoneConfig]
    event_types: List[str]

    @model_validator(mode="after")
    def _cross_validate(self) -> "CampusConfig":
        errors: List[str] = []

        node_ids = {n.id for n in self.nodes}

        # 1. Road from/to node ids exist
        for r in self.roads:
            if r.from_node not in node_ids:
                errors.append(f"Road '{r.id}' references missing from-node '{r.from_node}'")
            if r.to_node not in node_ids:
                errors.append(f"Road '{r.id}' references missing to-node '{r.to_node}'")

        # 2. Gate node ids exist
        for g in self.gates:
            if g.node not in node_ids:
                errors.append(f"Gate '{g.id}' references missing node '{g.node}'")

        # 3. Lot entrance_node ids exist
        for p in self.parking_lots:
            if p.entrance_node not in node_ids:
                errors.append(f"Lot '{p.id}' references missing entrance_node '{p.entrance_node}'")

        # 4. Lot capacity > 0
        for p in self.parking_lots:
            if p.capacity <= 0:
                errors.append(f"Lot '{p.id}' capacity must be > 0 (got {p.capacity})")

        # 5. reserved.total <= capacity
        for p in self.parking_lots:
            if p.reserved.total > p.capacity:
                errors.append(
                    f"Lot '{p.id}': reserved total ({p.reserved.total}) exceeds capacity ({p.capacity})"
                )

        # 6. Gate service_rate_vph > 0
        for g in self.gates:
            if g.service_rate_vph <= 0:
                errors.append(f"Gate '{g.id}' service_rate_vph must be > 0 (got {g.service_rate_vph})")

        # 7. Unique IDs
        def _check_dup(items: list, label: str) -> None:
            seen: set = set()
            for item in items:
                iid = item.id
                if iid in seen:
                    errors.append(f"Duplicate {label} id: '{iid}'")
                seen.add(iid)

        _check_dup(self.nodes, "node")
        _check_dup(self.gates, "gate")
        _check_dup(self.roads, "road")
        _check_dup(self.parking_lots, "lot")
        _check_dup(self.zones, "zone")

        # 8. Every open lot is reachable from at least one open gate (BFS on open roads)
        open_gate_nodes = {g.node for g in self.gates if g.status == "open"}
        open_lot_nodes = {p.entrance_node for p in self.parking_lots if p.status == "open"}

        # Build adjacency from open roads only
        adj: Dict[str, List[str]] = {n: [] for n in node_ids}
        for r in self.roads:
            if r.status == "open":
                adj[r.from_node].append(r.to_node)

        def _reachable_from_gates(target: str) -> bool:
            visited: set = set()
            stack = list(open_gate_nodes)
            while stack:
                cur = stack.pop()
                if cur == target:
                    return True
                if cur in visited:
                    continue
                visited.add(cur)
                stack.extend(adj.get(cur, []))
            return False

        if open_gate_nodes:
            for lot in self.parking_lots:
                if lot.status == "open":
                    if not _reachable_from_gates(lot.entrance_node):
                        errors.append(
                            f"Lot '{lot.id}' (entrance_node='{lot.entrance_node}') is not reachable "
                            f"from any open gate via open roads"
                        )

        if errors:
            raise ValueError("CampusConfig validation failed:\n" + "\n".join(f"  - {e}" for e in errors))

        return self


# ── Functions ────────────────────────────────────────────────────────────────

def load_campus(campus_id: str, config_dir: str = "configs/campus") -> CampusConfig:
    """Load and validate a campus YAML file. Raises ValidationError on failure."""
    # Support both absolute and relative config_dir
    config_path = Path(config_dir)
    if not config_path.is_absolute():
        # Try relative to cwd first, then relative to this file's repo root
        cwd_path = Path.cwd() / config_path / f"{campus_id}.yaml"
        root_path = Path(__file__).resolve().parent.parent.parent / config_path / f"{campus_id}.yaml"
        if cwd_path.exists():
            yaml_path = cwd_path
        elif root_path.exists():
            yaml_path = root_path
        else:
            raise FileNotFoundError(
                f"Campus config not found for '{campus_id}'. "
                f"Looked in: {cwd_path}, {root_path}"
            )
    else:
        yaml_path = config_path / f"{campus_id}.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Campus config not found: {yaml_path}")

    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    campus_raw = raw.get("campus", raw)  # support top-level campus key
    return CampusConfig.model_validate(campus_raw)


def build_digraph(campus: CampusConfig) -> nx.DiGraph:
    """Build a networkx DiGraph. Edge weight = travel_time_sec."""
    g = nx.DiGraph()
    for node in campus.nodes:
        g.add_node(node.id, lat=node.lat, lon=node.lon, node_type=node.type, name=node.name)
    for road in campus.roads:
        g.add_edge(
            road.from_node,
            road.to_node,
            road_id=road.id,
            weight=road.travel_time_sec,
            length_m=road.length_m,
            status=road.status,
        )
    return g


def plot_campus(campus: CampusConfig, output_path: str) -> str:
    """Draw the campus graph and save as PNG. Returns the output path."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    g = build_digraph(campus)

    # Position nodes by (lon, lat) for geographic layout
    pos = {n.id: (n.lon, n.lat) for n in campus.nodes}

    # Color by node type
    color_map = {"gate": "green", "junction": "blue", "lot_entrance": "red"}
    node_colors = [color_map.get(g.nodes[n].get("node_type", "junction"), "gray") for n in g.nodes]

    fig, ax = plt.subplots(figsize=(14, 10))
    nx.draw_networkx_nodes(g, pos, node_color=node_colors, node_size=500, ax=ax)
    nx.draw_networkx_labels(g, pos, font_size=8, font_color="white", ax=ax)
    nx.draw_networkx_edges(g, pos, edge_color="gray", arrows=True, arrowsize=15, ax=ax)

    # Edge labels skipped (DiGraph curved-arrow label bug in this networkx version)

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="green", label="Gate"),
        Patch(facecolor="blue", label="Junction"),
        Patch(facecolor="red", label="Lot Entrance"),
    ]
    ax.legend(handles=legend_elements, loc="upper left")
    ax.set_title(f"Campus Graph: {campus.name} ({campus.id})")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(str(out), dpi=150)
    plt.close(fig)
    return str(out)
