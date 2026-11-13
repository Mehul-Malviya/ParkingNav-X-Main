"""Campus schema — Pydantic models for gates, lots, roads, nodes, zones."""
from digital_twin.simulation.campus_config import (
    CampusConfig,
    GateConfig,
    ParkingLotConfig,
    RoadConfig,
    NodeConfig,
    ZoneConfig,
    build_digraph,
    load_campus,
    plot_campus,
)

__all__ = [
    "CampusConfig",
    "GateConfig",
    "ParkingLotConfig",
    "RoadConfig",
    "NodeConfig",
    "ZoneConfig",
    "build_digraph",
    "load_campus",
    "plot_campus",
]
