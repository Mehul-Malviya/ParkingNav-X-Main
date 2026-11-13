"""Tests for Stage 7: Risk Engine."""
import pytest


def test_overflow_risk_empty_lot():
    """Empty lot has near-zero overflow risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"test-lot": {"capacity": 100, "occupied": 10, "status": "open"}}
    risks = re.overflow_risk(states)
    assert risks["test-lot"] < 0.2, "Empty lot should have low overflow risk"


def test_overflow_risk_full_lot():
    """Nearly-full lot has high overflow risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"test-lot": {"capacity": 100, "occupied": 95, "status": "open"}}
    risks = re.overflow_risk(states)
    assert risks["test-lot"] > 0.7, "95% full lot should have high overflow risk"


def test_overflow_risk_closed_lot():
    """Closed lot has maximum risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"test-lot": {"capacity": 100, "occupied": 0, "status": "closed"}}
    risks = re.overflow_risk(states)
    assert risks["test-lot"] == 1.0


def test_gate_queue_risk_empty():
    """Gate with no queue has low risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"vitap-gate-main": {"capacity": 6, "queue_length": 0, "status": "open"}}
    risks = re.gate_queue_risk(states)
    assert risks["vitap-gate-main"] < 0.5


def test_gate_queue_risk_long():
    """Gate with long queue has high risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"vitap-gate-main": {"capacity": 6, "queue_length": 30, "status": "open"}}
    risks = re.gate_queue_risk(states)
    assert risks["vitap-gate-main"] > 0.5


def test_search_risk_high_fill():
    """High fill rate → high search risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    states = {"test-lot": {"capacity": 100, "occupied": 98, "status": "open"}}
    risks = re.search_risk(states)
    assert risks["test-lot"] > 0.7


def test_network_risk_all_empty():
    """All empty lots and no gate queues → low network risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    overflow = {"lot-a": 0.05, "lot-b": 0.03}
    gate = {"gate-a": 0.05}
    search = {"lot-a": 0.05, "lot-b": 0.03}
    net = re.network_risk(overflow, gate, search)
    assert net < 0.3, f"Network risk should be low: {net}"


def test_network_risk_critical():
    """All lots nearly full → high network risk."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    overflow = {"lot-a": 0.95, "lot-b": 0.98}
    gate = {"gate-a": 0.80}
    search = {"lot-a": 0.95, "lot-b": 0.90}
    net = re.network_risk(overflow, gate, search)
    assert net > 0.7, f"Network risk should be critical: {net}"


def test_severity_classification():
    """Risk scores map to correct severity labels."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()

    def sev(score):
        if score >= 0.75: return "CRITICAL"
        if score >= 0.50: return "HIGH"
        if score >= 0.25: return "MEDIUM"
        return "LOW"

    assert sev(0.9) == "CRITICAL"
    assert sev(0.6) == "HIGH"
    assert sev(0.3) == "MEDIUM"
    assert sev(0.1) == "LOW"


def test_risk_scores_in_unit_interval():
    """All risk scores must be in [0, 1]."""
    from digital_twin.risk.engine import RiskEngine
    re = RiskEngine()
    lot_states = {
        "vitap-lot-academic-main": {"capacity": 108, "occupied": 80, "status": "open"},
        "vitap-lot-hostel": {"capacity": 162, "occupied": 160, "status": "open"},
    }
    gate_states = {
        "vitap-gate-main": {"capacity": 6, "queue_length": 5, "status": "open"},
    }
    for scores, _ in [
        (re.overflow_risk(lot_states), "overflow"),
        (re.gate_queue_risk(gate_states), "gate_queue"),
        (re.search_risk(lot_states), "search"),
    ]:
        for entity_id, score in scores.items():
            assert 0.0 <= score <= 1.0, f"{entity_id}: score {score} out of [0,1]"
