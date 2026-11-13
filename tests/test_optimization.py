"""Tests for Stage 8: Optimization Engine."""
import pytest


def test_weight_profiles_sum_to_one():
    """All weight profiles must have weights summing to 1."""
    from digital_twin.optimization.engine import WEIGHT_PROFILES
    for name, weights in WEIGHT_PROFILES.items():
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-9, f"Profile {name} weights sum to {total}"


def test_cost_components_in_unit_interval():
    """All cost components return values in [0, 1]."""
    from digital_twin.optimization.engine import CostComponents, MultiObjectiveOptimizer
    cc = CostComponents()
    lot_fills = {
        "vitap-lot-academic-main": 0.85,
        "vitap-lot-hostel": 0.60,
        "vitap-lot-admin-visitor": 0.95,
        "vitap-lot-sports": 0.40,
        "vitap-lot-overflow": 0.20,
    }
    gate_states = {
        "vitap-gate-main": {"capacity": 6, "queue_length": 8},
    }
    c1 = cc.waiting_time_cost(gate_states)
    c2 = cc.queue_cost(gate_states)
    c3 = cc.search_travel_cost(lot_fills)
    c4 = cc.utilization_imbalance(lot_fills)
    c5 = cc.overflow_penalty(lot_fills)

    for label, val in [("c1", c1), ("c2", c2), ("c3", c3), ("c4", c4), ("c5", c5)]:
        assert 0.0 <= val <= 1.0, f"{label} = {val} out of [0, 1]"


def test_objective_J_in_unit_interval():
    """Objective J must be in [0, 1]."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    opt = MultiObjectiveOptimizer(weight_profile="P1")
    lot_fills = {
        "vitap-lot-academic-main": 0.85,
        "vitap-lot-hostel": 0.60,
        "vitap-lot-admin-visitor": 0.95,
        "vitap-lot-sports": 0.40,
        "vitap-lot-overflow": 0.20,
    }
    gate_states = {"vitap-gate-main": {"capacity": 6, "queue_length": 5}}
    cost = opt.compute_cost(lot_fills, gate_states)
    assert 0.0 <= cost["J"] <= 1.0, f"J = {cost['J']} out of [0, 1]"
    assert all(k in cost for k in ["waiting_time", "queue_cost", "search_travel", "utilization_imbalance", "overflow_penalty"])


def test_proactive_trigger_fires():
    """Proactive trigger fires when forecast > 90% and current < 90%."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    opt = MultiObjectiveOptimizer()
    current_fills = {"vitap-lot-academic-main": 0.85}
    forecast_fills = {"vitap-lot-academic-main": 0.95}  # forecast > 90%
    alerts = opt._check_proactive_trigger(current_fills, forecast_fills)
    assert len(alerts) >= 1
    assert alerts[0]["lot_id"] == "vitap-lot-academic-main"
    assert alerts[0]["type"] == "PROACTIVE_REROUTE"


def test_proactive_trigger_does_not_fire_when_reactive():
    """Proactive trigger should NOT fire when current already >= 90% (reactive, not proactive)."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    opt = MultiObjectiveOptimizer()
    current_fills = {"vitap-lot-academic-main": 0.95}   # already full
    forecast_fills = {"vitap-lot-academic-main": 0.98}
    alerts = opt._check_proactive_trigger(current_fills, forecast_fills)
    assert len(alerts) == 0, "Should not fire when already at capacity"


def test_lot_ranking_order():
    """Lots with lower fill rates should be ranked earlier (more available)."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    opt = MultiObjectiveOptimizer()
    lot_fills = {
        "vitap-lot-academic-main": 0.90,
        "vitap-lot-hostel": 0.20,
        "vitap-lot-admin-visitor": 0.70,
        "vitap-lot-sports": 0.50,
        "vitap-lot-overflow": 0.30,
    }
    ranked = opt._rank_lots(lot_fills, None)
    # First ranked should be the least full
    assert ranked[0]["current_fill_rate"] < ranked[-1]["current_fill_rate"]


def test_utilization_imbalance_zero_for_uniform():
    """Imbalance should be near zero when all lots have equal fill rates."""
    from digital_twin.optimization.engine import CostComponents
    cc = CostComponents()
    uniform = {lid: 0.5 for lid in ["a", "b", "c", "d", "e"]}
    imb = cc.utilization_imbalance(uniform)
    assert imb < 0.01, f"Uniform fill should have ~0 imbalance, got {imb}"


def test_overflow_penalty_zero_for_low_fill():
    """No overflow penalty when all lots below 95% fill."""
    from digital_twin.optimization.engine import CostComponents
    cc = CostComponents()
    fills = {"a": 0.5, "b": 0.7, "c": 0.8, "d": 0.89, "e": 0.3}
    penalty = cc.overflow_penalty(fills)
    assert penalty == 0.0, "No lots over 95% should mean zero overflow penalty"


def test_recommendation_has_objective_score_and_why_chosen():
    """LOT_RANKING recommendation must include objective_score and why_chosen fields."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    from digital_twin.db import get_connection, apply_migrations
    from digital_twin.config_loader import load_campus_config
    from pathlib import Path

    ROOT = Path(__file__).resolve().parent.parent
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(ROOT / "configs" / "campus" / "vitap.yaml", conn)

    opt = MultiObjectiveOptimizer(weight_profile="P2")
    recs = opt.generate_recommendations(conn)
    conn.close()

    # Find the LOT_RANKING recommendation
    lot_ranking = next((r for r in recs if r.get("type") == "LOT_RANKING"), None)
    assert lot_ranking is not None, "Expected a LOT_RANKING recommendation"
    assert "objective_score" in lot_ranking, "LOT_RANKING must include objective_score"
    assert isinstance(lot_ranking["objective_score"], float), "objective_score must be float"
    assert 0.0 <= lot_ranking["objective_score"] <= 1.0, "objective_score must be in [0, 1]"
    assert "why_chosen" in lot_ranking, "LOT_RANKING must include why_chosen"
    assert isinstance(lot_ranking["why_chosen"], str), "why_chosen must be a string"
    assert len(lot_ranking["why_chosen"]) > 10, "why_chosen must be a non-trivial sentence"
    assert "alternatives" in lot_ranking, "LOT_RANKING must include alternatives list"

    # Each ranked lot should also have objective_score and rank
    ranked = lot_ranking.get("ranked_lots", [])
    assert len(ranked) > 0, "ranked_lots must not be empty"
    assert "objective_score" in ranked[0], "Each ranked lot must have objective_score"
    assert "rank" in ranked[0], "Each ranked lot must have rank field"
    assert ranked[0]["rank"] == 1, "Best lot should have rank=1"


def test_all_weight_profiles_produce_valid_J():
    """All three weight profiles produce valid J values."""
    from digital_twin.optimization.engine import MultiObjectiveOptimizer, WEIGHT_PROFILES
    lot_fills = {"vitap-lot-academic-main": 0.75, "vitap-lot-hostel": 0.50}
    gate_states = {"vitap-gate-main": {"capacity": 6, "queue_length": 3}}
    for profile in WEIGHT_PROFILES:
        opt = MultiObjectiveOptimizer(weight_profile=profile)
        cost = opt.compute_cost(lot_fills, gate_states)
        assert 0.0 <= cost["J"] <= 1.0, f"Profile {profile}: J out of range"


# ---- weight profiles must actually change what the optimizer reports -------------------------

STRESSED_CURRENT = {
    "vitap-lot-academic-main": 0.93, "vitap-lot-hostel": 0.55, "vitap-lot-admin-visitor": 0.80,
    "vitap-lot-sports": 0.30, "vitap-lot-overflow": 0.20,
}
STRESSED_FORECAST = {
    "vitap-lot-academic-main": 0.97, "vitap-lot-hostel": 0.60, "vitap-lot-admin-visitor": 0.88,
    "vitap-lot-sports": 0.35, "vitap-lot-overflow": 0.25,
}
STRESSED_GATES = {"vitap-gate-main": {"capacity": 6, "queue_length": 12},
                  "vitap-gate-visitor": {"capacity": 3, "queue_length": 2}}


def test_cost_function_exposes_profile_weights_and_contributions_that_sum_to_J():
    from digital_twin.optimization.engine import MultiObjectiveOptimizer, WEIGHT_PROFILES
    seen = {}
    for profile in WEIGHT_PROFILES:
        cost = MultiObjectiveOptimizer(profile).compute_cost(STRESSED_CURRENT, STRESSED_GATES)
        assert cost["weights"] == WEIGHT_PROFILES[profile]
        assert abs(sum(cost["weighted"].values()) - cost["J"]) < 1e-3
        seen[profile] = cost
    # raw component costs do not depend on the profile; weights and contributions do
    for k in ("waiting_time", "queue_cost", "search_travel", "utilization_imbalance", "overflow_penalty"):
        assert seen["P1"][k] == seen["P2"][k] == seen["P3"][k], k
    assert seen["P1"]["weighted"] != seen["P3"]["weighted"]
    assert len({c["J"] for c in seen.values()}) == 3, "each profile should give a different J"


def test_lot_ranking_scores_depend_on_the_weight_profile():
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    results = {}
    for profile in ("P1", "P2", "P3"):
        ranked = MultiObjectiveOptimizer(profile)._rank_lots(STRESSED_CURRENT, STRESSED_FORECAST, STRESSED_GATES)
        assert [r["rank"] for r in ranked] == [1, 2, 3, 4, 5]
        assert all(0.0 <= r["objective_score"] <= 1.0 for r in ranked)
        assert [r["objective_score"] for r in ranked] == sorted(r["objective_score"] for r in ranked)
        results[profile] = {r["lot_id"]: r["objective_score"] for r in ranked}
    assert results["P1"] != results["P2"] != results["P3"]
    # the overflow-weighted profile penalises the near-full lots harder than the wait-weighted one
    gap = lambda s: s["vitap-lot-academic-main"] - s["vitap-lot-overflow"]
    assert gap(results["P3"]) > gap(results["P1"])


def _db_with_campus():
    from digital_twin.db import get_connection, apply_migrations
    from digital_twin.config_loader import load_campus_config
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(root / "configs" / "campus" / "vitap.yaml", conn)
    return conn


def test_current_fill_is_recorded_occupancy_else_forecast_not_a_made_up_default():
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    conn = _db_with_campus()
    rec = next(r for r in MultiObjectiveOptimizer("P2").generate_recommendations(conn) if r["type"] == "LOT_RANKING")
    # no occupancy history yet: figures come from the forecast, never the old fixed 0.4
    assert {l["current_fill_source"] for l in rec["ranked_lots"]} <= {"forecast", "default"}
    for l in rec["ranked_lots"]:
        if l["current_fill_source"] == "forecast":
            assert l["current_fill_rate"] == l["forecast_fill_rate_15min"]

    conn.execute("INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate) VALUES (?, ?, ?)",
                 ("vitap-lot-hostel", 81, 0.5))
    conn.commit()
    rec = next(r for r in MultiObjectiveOptimizer("P2").generate_recommendations(conn) if r["type"] == "LOT_RANKING")
    hostel = next(l for l in rec["ranked_lots"] if l["lot_id"] == "vitap-lot-hostel")
    assert hostel["current_fill_source"] == "recorded"
    assert abs(hostel["current_fill_rate"] - 81 / 162) < 1e-3
    conn.close()


def test_lot_ranking_recommendation_names_the_profile():
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    conn = _db_with_campus()
    outs = {}
    for profile in ("P1", "P3"):
        rec = next(r for r in MultiObjectiveOptimizer(profile).generate_recommendations(conn)
                   if r["type"] == "LOT_RANKING")
        assert profile in rec["message"] and profile in rec["why_chosen"]
        outs[profile] = rec["cost_function"]["weighted"]
    assert outs["P1"] != outs["P3"]
    conn.close()


# ---- lot names / capacities / open status come from the campus DB, not constants -------------

def test_ranking_uses_database_lot_names_capacity_and_status():
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    conn = _db_with_campus()
    conn.execute("UPDATE parking_lots SET name='Renamed Hostel Lot', usable_capacity=1000 "
                 "WHERE parking_lot_id='vitap-lot-hostel'")
    conn.execute("UPDATE parking_lots SET status='closed' WHERE parking_lot_id='vitap-lot-sports'")
    conn.commit()
    rec = next(r for r in MultiObjectiveOptimizer("P2").generate_recommendations(conn) if r["type"] == "LOT_RANKING")
    by_id = {l["lot_id"]: l for l in rec["ranked_lots"]}
    assert "vitap-lot-sports" not in by_id, "a closed lot must never be recommended"
    hostel = by_id["vitap-lot-hostel"]
    assert hostel["lot_name"] == "Renamed Hostel Lot"
    assert hostel["capacity"] == 1000
    # free spaces scale with the DB capacity (fill is rounded to 3 decimals in the output, so allow 1)
    assert abs(hostel["available_spaces"] - (1.0 - hostel["forecast_fill_rate_15min"]) * 1000) <= 1
    # names match the campus config, so the panel and the map agree
    assert by_id["vitap-lot-overflow"]["lot_name"] == "Overflow Parking"
    conn.close()


def test_profiles_endpoint_serves_the_real_weights(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import digital_twin.api.app as api
    from digital_twin.optimization.engine import WEIGHT_PROFILES
    monkeypatch.setattr(api, "DB_PATH", tmp_path / "p.db")
    with TestClient(api.app) as c:
        body = c.get("/optimize/profiles").json()["profiles"]
    assert [p["id"] for p in body] == list(WEIGHT_PROFILES)
    for p in body:
        assert p["weights"] == WEIGHT_PROFILES[p["id"]]
        assert abs(sum(p["weights"].values()) - 1.0) < 1e-9
        assert p["label"].startswith(p["id"]) and p["description"]


# ---- the numbers in the panel must reconcile with each other ---------------------------------

def _lot_ranking(conn, profile):
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    return next(r for r in MultiObjectiveOptimizer(profile).generate_recommendations(conn)
                if r["type"] == "LOT_RANKING")


def test_system_J_and_per_lot_J_share_one_basis_and_reconcile():
    conn = _db_with_campus()
    for profile in ("P1", "P2", "P3"):
        rec = _lot_ranking(conn, profile)
        sysJ = rec["cost_function"]["J"]
        # contributions add up to the system J (components are rounded to 4 dp)
        assert abs(sum(rec["cost_function"]["weighted"].values()) - sysJ) < 5e-4
        for lot in rec["ranked_lots"]:
            # per-lot J is the SAME system J plus the effect of sending vehicles there
            assert abs((lot["objective_score"] - lot["objective_delta"]) - sysJ) < 5e-4, (profile, lot["lot_id"])
    conn.close()


def test_stale_occupancy_snapshot_is_not_treated_as_current():
    conn = _db_with_campus()
    conn.execute("INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, recorded_at) "
                 "VALUES ('vitap-lot-overflow', 40, 0.87, datetime('now', '-3 hours'))")
    conn.commit()
    lot = next(l for l in _lot_ranking(conn, "P2")["ranked_lots"] if l["lot_id"] == "vitap-lot-overflow")
    assert lot["current_fill_source"] == "forecast"
    assert lot["current_fill_rate"] == lot["forecast_fill_rate_15min"]
    assert 170 <= lot["stale_snapshot_min"] <= 190
    conn.close()


def test_fresh_occupancy_snapshot_is_used_as_current():
    conn = _db_with_campus()
    conn.execute("INSERT INTO lot_occupancy_history (lot_id, occupied_spaces, fill_rate, recorded_at) "
                 "VALUES ('vitap-lot-overflow', 23, 0.5, datetime('now', '-5 minutes'))")
    conn.commit()
    lot = next(l for l in _lot_ranking(conn, "P2")["ranked_lots"] if l["lot_id"] == "vitap-lot-overflow")
    assert lot["current_fill_source"] == "recorded"
    assert abs(lot["current_fill_rate"] - 23 / 46) < 1e-3
    assert "stale_snapshot_min" not in lot
    conn.close()


# ---- wait / queue weights must be able to change the lot choice -------------------------------

EQUAL_FILLS = {k: 0.3 for k in ("vitap-lot-academic-main", "vitap-lot-hostel", "vitap-lot-admin-visitor",
                                "vitap-lot-sports", "vitap-lot-overflow")}
FREE = {"vitap-gate-main": {"capacity": 6, "queue_length": 0}, "vitap-gate-visitor": {"capacity": 3, "queue_length": 0}}
MAIN_JAMMED = {"vitap-gate-main": {"capacity": 6, "queue_length": 18}, "vitap-gate-visitor": {"capacity": 3, "queue_length": 0}}


def _ranked(conn, profile, gates):
    from digital_twin.optimization.engine import MultiObjectiveOptimizer
    opt = MultiObjectiveOptimizer(profile)
    opt._load_lots(conn)
    return {l["lot_id"]: l for l in opt._rank_lots(EQUAL_FILLS, EQUAL_FILLS, gates)}


def test_lots_know_which_open_gates_reach_them():
    conn = _db_with_campus()
    r = _ranked(conn, "P1", FREE)
    assert r["vitap-lot-sports"]["access_gates"] == ["vitap-gate-main"]      # drive road from the main gate only
    assert set(r["vitap-lot-hostel"]["access_gates"]) == {"vitap-gate-main", "vitap-gate-visitor"}
    conn.close()


def test_wait_and_queue_weights_change_which_lot_is_recommended_when_a_gate_is_jammed():
    conn = _db_with_campus()
    penalty = {}
    for profile in ("P1", "P2", "P3"):
        free, jam = _ranked(conn, profile, FREE), _ranked(conn, profile, MAIN_JAMMED)
        # the lot reachable only through the jammed gate is pushed down; lots with a free gate are not
        assert jam["vitap-lot-sports"]["rank"] == 5, profile
        assert jam["vitap-lot-sports"]["rank"] > free["vitap-lot-sports"]["rank"]
        assert jam["vitap-lot-hostel"]["objective_score"] == free["vitap-lot-hostel"]["objective_score"]
        penalty[profile] = jam["vitap-lot-sports"]["objective_score"] - free["vitap-lot-sports"]["objective_score"]
    # the wait-weighted profile punishes the jammed route hardest, the overflow-weighted one least
    assert penalty["P1"] > penalty["P2"] > penalty["P3"] > 0
    conn.close()


def test_closed_gate_is_not_used_to_reach_a_lot():
    conn = _db_with_campus()
    conn.execute("UPDATE gates SET status='closed' WHERE gate_id='vitap-gate-visitor'")
    conn.commit()
    r = _ranked(conn, "P1", {"vitap-gate-main": FREE["vitap-gate-main"]})
    assert r["vitap-lot-hostel"]["access_gates"] == ["vitap-gate-main"]
    conn.close()
