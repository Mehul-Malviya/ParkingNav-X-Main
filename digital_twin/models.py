"""Shared enums/constants for the Digital Twin + Simulation subsystem."""

from enum import Enum


class Provenance(str, Enum):
    REAL = "REAL"
    SYNTHETIC = "SYNTHETIC"
    SAMPLE = "SAMPLE"
    # Extended per a second Member 1 spec version -- purely additive, no
    # conflict with the three values above. Not all are produced by this
    # module today (e.g. PREDICTION/DERIVED belong to other members'
    # modules), but the enum accepts them so state written by those modules
    # through this same Digital Twin never needs an ambiguous provenance.
    HISTORICAL = "HISTORICAL"
    PREDICTION = "PREDICTION"
    DERIVED = "DERIVED"
    COUNTERFACTUAL = "COUNTERFACTUAL"


class EntityStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESTRICTED = "restricted"
    BLOCKED = "blocked"


class FreshnessState(str, Enum):
    FRESH = "FRESH"
    AGING = "AGING"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class Source(str, Enum):
    MANUAL = "manual"
    CV_AUTO = "cv_auto"
    CV_VERIFIED = "cv_verified"
    SIMULATION = "simulation"
    REAL = "real"


class VehicleLifecycleState(str, Enum):
    APPROACHING = "approaching"
    WAITING = "waiting"
    ENTERING = "entering"
    SEARCHING = "searching"
    ASSIGNED = "assigned"
    PARKED = "parked"
    LEAVING = "leaving"
    COMPLETED = "completed"


# Freshness thresholds in minutes, per entity type: (fresh_below, aging_below).
# >= aging_below is STALE. No observation at all is UNKNOWN.
FRESHNESS_THRESHOLDS_MINUTES = {
    "parking": (10, 30),
    "gate": (5, 15),
    "road": (5, 15),
}


class ConfigError(ValueError):
    """Raised on any campus/scenario configuration problem. Never silently repaired."""
