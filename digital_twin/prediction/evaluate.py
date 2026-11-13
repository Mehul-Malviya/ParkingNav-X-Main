"""
Stage 6 evaluation: compute MAE, RMSE, MAPE, coverage metrics.
Saves results to experiments/results/prediction_metrics.json.
"""

import json
import math
from pathlib import Path

import numpy as np

from digital_twin.prediction.features import LOT_IDS, build_features, load_data

RESULTS_DIR = Path(__file__).resolve().parent.parent.parent / "experiments" / "results"


def evaluate_predictor(predictor_name: str, predictions: np.ndarray, targets: np.ndarray) -> dict:
    """Compute MAE, RMSE, MAPE, WAPE, R² for a set of predictions vs targets."""
    errors = predictions - targets
    mae = float(np.mean(np.abs(errors)))
    rmse = float(math.sqrt(np.mean(errors ** 2)))
    # MAPE: skip targets near zero
    mask = np.abs(targets) > 0.01
    mape = float(np.mean(np.abs(errors[mask] / targets[mask])) * 100) if mask.any() else float("nan")
    # WAPE (Weighted Absolute Percentage Error): sum(|e|) / sum(|target|)
    sum_targets = float(np.sum(np.abs(targets)))
    wape = float(np.sum(np.abs(errors)) / sum_targets * 100) if sum_targets > 0 else float("nan")
    # R²
    ss_res = float(np.sum(errors ** 2))
    ss_tot = float(np.sum((targets - targets.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "predictor": predictor_name,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4) if not math.isnan(r2) else None,
        "mape_pct": round(mape, 2) if not math.isnan(mape) else None,
        "wape_pct": round(wape, 2) if not math.isnan(wape) else None,
        "n_samples": int(len(predictions)),
    }


def evaluate_coverage(lower: np.ndarray, upper: np.ndarray, targets: np.ndarray) -> float:
    """Compute empirical coverage of prediction intervals."""
    covered = ((targets >= lower) & (targets <= upper)).sum()
    return float(covered / len(targets))


def run_evaluation(horizon_minutes: int = 15):
    """Run full evaluation across all lots and save results."""
    from digital_twin.prediction.engine import (
        HistoricalAveragePredictor, MovingAveragePredictor, XGBoostPredictor
    )

    df = load_data()
    horizon_steps = max(1, horizon_minutes // 15)
    all_results = []

    for lot_id in LOT_IDS:
        X, y, ts = build_features(df, lot_id, horizon_steps)
        if len(X) < 50:
            continue

        n = len(X)
        n_train = int(n * 0.70)
        n_cal = int(n * 0.85)
        X_test, y_test = X[n_cal:], y[n_cal:]

        if len(X_test) == 0:
            continue

        # Historical Average
        ha = HistoricalAveragePredictor()
        ha.fit(df, lot_id, horizon_steps)

        lot_df = df[df["lot_id"] == lot_id] if "lot_id" in df.columns else df
        lot_df = lot_df.sort_values("timestamp").reset_index(drop=True)
        if "fill_rate" not in lot_df.columns:
            from digital_twin.prediction.features import LOT_CAPACITIES
            cap = LOT_CAPACITIES.get(lot_id, 100)
            lot_df["fill_rate"] = lot_df.get("occupied", 0) / cap

        test_lot = lot_df.iloc[int(len(lot_df) * 0.85):]
        if len(test_lot) == 0:
            continue

        ha_preds = np.array([
            ha.predict_slot(lot_id, int(r["hour"]), int(r["day_of_week"]))
            for _, r in test_lot.iterrows()
        ])
        y_test_lot = test_lot["fill_rate"].values
        min_len = min(len(ha_preds), len(y_test_lot))
        ha_preds = ha_preds[:min_len]
        y_test_lot = y_test_lot[:min_len]

        # MovingAverage on test portion
        from digital_twin.prediction.engine import MovingAveragePredictor
        ma = MovingAveragePredictor()
        ma.fit(df, lot_id, horizon_steps)
        ma_preds = np.array([ma.predict(lot_id)] * min_len)

        result = {
            "lot_id": lot_id,
            "horizon_minutes": horizon_minutes,
            "historical_average": evaluate_predictor("HistoricalAverage", ha_preds, y_test_lot),
            "moving_average": evaluate_predictor("MovingAverage", ma_preds, y_test_lot),
        }

        # XGBoost
        try:
            xgb = XGBoostPredictor()
            xgb.fit(df, lot_id, horizon_steps)
            if lot_id in xgb._models:
                xgb_preds = xgb._models[lot_id].predict(X_test)
                xgb_preds = np.clip(xgb_preds, 0, 1)
                result["xgboost"] = evaluate_predictor("XGBoost", xgb_preds, y_test)
                # Coverage
                w = xgb._conformal_width.get(lot_id, 0.1)
                lower = np.clip(xgb_preds - w, 0, 1)
                upper = np.clip(xgb_preds + w, 0, 1)
                result["xgboost"]["coverage_90"] = round(evaluate_coverage(lower, upper, y_test), 4)
        except Exception:
            pass

        all_results.append(result)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "prediction_metrics.json"
    with open(out_path, "w") as f:
        json.dump({"horizon_minutes": horizon_minutes, "lots": all_results}, f, indent=2)

    return all_results


if __name__ == "__main__":
    results = run_evaluation()
    for r in results:
        ha = r.get("historical_average", {})
        ma = r.get("moving_average", {})
        xgb = r.get("xgboost", {})
        print(
            f"{r['lot_id']}: "
            f"HA MAE={ha.get('mae')} WAPE={ha.get('wape_pct')}% R²={ha.get('r2')} | "
            f"MA MAE={ma.get('mae')} WAPE={ma.get('wape_pct')}% R²={ma.get('r2')} | "
            f"XGB MAE={xgb.get('mae')} WAPE={xgb.get('wape_pct')}% R²={xgb.get('r2')} "
            f"coverage={xgb.get('coverage_90')}"
        )
