"""
Stage 6: Prediction Engine — three predictors + conformal prediction intervals.

Predictors:
  HistoricalAveragePredictor  — mean of same (hour, dow) slot across history
  MovingAveragePredictor      — exponential moving average of recent readings
  XGBoostPredictor            — XGBoost regressor with conformal intervals

Train/val/test split: days 1-21 train, 22-25 validate, 26-30 test.
Conformal prediction: residuals on calibration set → 90% coverage interval.
"""

import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Optional

import numpy as np

from digital_twin.prediction.features import (
    LOT_CAPACITIES, LOT_IDS, build_features, load_data
)

LIVE_HALF_LIFE_MIN = 60  # how fast an observed deviation from the typical level fades
_PREDICTOR_SINGLETON: Optional["PredictionEngine"] = None
_DEMAND_DF = None  # cached DataFrame — loaded once, reused by all predict() calls
MODEL_DIR = Path(__file__).resolve().parent.parent.parent / "experiments" / "models"


def _get_demand_df():
    """Return the demand DataFrame, loading it once and caching it."""
    global _DEMAND_DF
    if _DEMAND_DF is None:
        _DEMAND_DF = load_data()
    return _DEMAND_DF


def retrain(conn=None):
    """Refit every model on current data: real recorded occupancy where a lot has enough, synthetic
    otherwise. Returns what each lot was trained on."""
    global _DEMAND_DF, _PREDICTOR_SINGLETON
    from digital_twin.prediction.features import real_lots
    _DEMAND_DF = load_data(conn)
    _PREDICTOR_SINGLETON = PredictionEngine()
    _PREDICTOR_SINGLETON.fit_all()
    real = real_lots(_DEMAND_DF)
    xgb = _PREDICTOR_SINGLETON._xgb._models
    return {"real_lots": real, "synthetic_lots": [l for l in LOT_IDS if l not in real],
            # a lot with real data but too many gaps for the 24 h lag features falls back to MovingAverage
            "lots_without_xgboost": [l for l in LOT_IDS if l not in xgb]}


def data_description() -> Dict:
    """Honest label for what the loaded models were trained on."""
    from digital_twin.prediction.features import real_lots
    real = real_lots(_get_demand_df())
    if not real:
        return {"mode": "synthetic", "real_lots": [], "label": "synthetic daily pattern"}
    mode = "real" if len(real) == len(LOT_IDS) else "mixed"
    return {"mode": mode, "real_lots": real,
            "label": ("trained on recorded occupancy" if mode == "real"
                      else f"trained on recorded occupancy for {len(real)} of {len(LOT_IDS)} lots, synthetic for the rest")}


class HistoricalAveragePredictor:
    """Predict based on historical mean for (hour, day_of_week) slot."""

    name = "HistoricalAverage"

    def __init__(self):
        self._table: Dict[str, Dict[tuple, float]] = defaultdict(dict)
        self._global_mean: Dict[str, float] = {}

    def fit(self, df, lot_id: str, horizon_steps: int = 1):
        import pandas as pd
        lot_df = df[df["lot_id"] == lot_id].copy() if "lot_id" in df.columns else df.copy()
        lot_df = lot_df.sort_values("timestamp").reset_index(drop=True)
        if "fill_rate" not in lot_df.columns:
            cap = LOT_CAPACITIES.get(lot_id, 100)
            lot_df["fill_rate"] = lot_df.get("occupied", 0) / cap
        # Ensure time columns exist (extract from timestamp if needed)
        if "hour" not in lot_df.columns and "timestamp" in lot_df.columns:
            ts = pd.to_datetime(lot_df["timestamp"])
            lot_df["hour"] = ts.dt.hour
            lot_df["day_of_week"] = ts.dt.dayofweek
        if "hour" not in lot_df.columns:
            lot_df["hour"] = 9
            lot_df["day_of_week"] = 0
        lot_df["target"] = lot_df["fill_rate"].shift(-horizon_steps)
        lot_df = lot_df.dropna(subset=["target"])
        n_train = int(len(lot_df) * 0.70)
        train = lot_df.iloc[:n_train]
        slot_means = train.groupby(["hour", "day_of_week"])["target"].mean().to_dict()
        self._table[lot_id] = slot_means
        self._global_mean[lot_id] = float(train["target"].mean())

    def predict_slot(self, lot_id: str, hour: int, dow: int) -> float:
        key = (hour, dow)
        table = self._table.get(lot_id, {})
        return table.get(key, self._global_mean.get(lot_id, 0.5))


class MovingAveragePredictor:
    """Exponential moving average of recent fill rates."""

    name = "MovingAverage"

    def __init__(self, alpha: float = 0.3):
        self.alpha = alpha
        self._ema: Dict[str, float] = {}
        self._residuals: Dict[str, list] = defaultdict(list)

    def fit(self, df, lot_id: str, horizon_steps: int = 1):
        import pandas as pd
        lot_df = df[df["lot_id"] == lot_id].copy() if "lot_id" in df.columns else df.copy()
        if "timestamp" in lot_df.columns:
            lot_df = lot_df.sort_values("timestamp").reset_index(drop=True)
        if "fill_rate" not in lot_df.columns:
            cap = LOT_CAPACITIES.get(lot_id, 100)
            occ_col = "occupied" if "occupied" in lot_df.columns else lot_df.columns[0]
            lot_df["fill_rate"] = lot_df.get(occ_col, 0) / cap
        n_train = int(len(lot_df) * 0.70)
        train = lot_df.iloc[:n_train]["fill_rate"].dropna().values
        ema = float(train[0]) if len(train) > 0 else 0.5
        residuals = []
        for v in train:
            v = float(v)
            residuals.append(abs(v - ema))
            ema = self.alpha * v + (1 - self.alpha) * ema
        self._ema[lot_id] = float(ema)
        self._residuals[lot_id] = residuals

    def update(self, lot_id: str, current_fill: float) -> float:
        prev = self._ema.get(lot_id, current_fill)
        new_ema = float(self.alpha * current_fill + (1 - self.alpha) * prev)
        self._ema[lot_id] = new_ema
        return new_ema

    def predict(self, lot_id: str) -> float:
        return self._ema.get(lot_id, 0.5)


class XGBoostPredictor:
    """XGBoost occupancy predictor with conformal prediction intervals."""

    name = "XGBoost"

    def __init__(self):
        self._models: Dict[str, object] = {}
        self._conformal_width: Dict[str, float] = {}

    def fit(self, df, lot_id: str, horizon_steps: int = 1):
        try:
            from xgboost import XGBRegressor
        except ImportError:
            return  # silently skip if xgboost not installed

        X, y, ts = build_features(df, lot_id, horizon_steps)
        if len(X) < 50:
            return

        # Train/val/test split: 70% train, 15% val (conformal calibration), 15% test
        n = len(X)
        n_train = int(n * 0.70)
        n_cal = int(n * 0.85)

        X_train, y_train = X[:n_train], y[:n_train]
        X_cal, y_cal = X[n_train:n_cal], y[n_train:n_cal]

        model = XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            verbosity=0,
        )
        model.fit(X_train, y_train, eval_set=[(X_cal, y_cal)], verbose=False)
        self._models[lot_id] = model

        # Conformal calibration: compute residuals on calibration set
        if len(X_cal) > 0:
            y_pred_cal = model.predict(X_cal)
            residuals = np.abs(y_cal - y_pred_cal)
            # 90% conformal quantile
            q90 = float(np.quantile(residuals, 0.90))
            self._conformal_width[lot_id] = q90
        else:
            self._conformal_width[lot_id] = 0.1

    def predict(self, lot_id: str, features: np.ndarray) -> Dict:
        model = self._models.get(lot_id)
        if model is None:
            return {"fill_rate": 0.5, "lower_90": 0.4, "upper_90": 0.6}
        pred = float(model.predict(features.reshape(1, -1))[0])
        pred = max(0.0, min(1.0, pred))
        w = self._conformal_width.get(lot_id, 0.1)
        return {
            "fill_rate": pred,
            "lower_90": max(0.0, pred - w),
            "upper_90": min(1.0, pred + w),
        }


class PredictionEngine:
    """
    Unified prediction engine — wraps all three predictors.
    Falls back gracefully: XGBoost → MovingAverage → HistoricalAverage.
    """

    def __init__(self):
        self._ha = HistoricalAveragePredictor()
        self._ma = MovingAveragePredictor()
        self._xgb = XGBoostPredictor()
        self._fitted = False
        self._current_fills: Dict[str, float] = {lid: 0.3 for lid in LOT_IDS}

    def fit_all(self, horizon_steps: int = 1):
        """Train all predictors on synthetic_multi_year_demand.csv."""
        df = _get_demand_df()
        for lot_id in LOT_IDS:
            self._ha.fit(df, lot_id, horizon_steps)
            self._ma.fit(df, lot_id, horizon_steps)
            self._xgb.fit(df, lot_id, horizon_steps)
        self._fitted = True

    def update_current(self, lot_id: str, fill_rate: float):
        """Update live fill rate (called by simulation or API)."""
        self._current_fills[lot_id] = max(0.0, min(1.0, fill_rate))
        self._ma.update(lot_id, fill_rate)

    def predict(self, lot_id: str, horizon_minutes: int = 15, at=None, live_fill=None) -> Dict:
        """
        Predict fill rate at horizon_minutes from now.
        Returns: {fill_rate, lower_90, upper_90, model}

        With no `at` / `live_fill` this is the original static behaviour (the model's input is the
        last row of the demand data); the simulation relies on that, so it must not change.
        With `at` (campus-local datetime) the input is the synthetic row for the same weekday and
        15-minute slot, so the forecast follows the time of day; `live_fill` (a fresh recorded
        occupancy) replaces the model's own current-fill input.
        """
        if not self._fitted:
            self.fit_all(horizon_steps=max(1, horizon_minutes // 15))

        if at is not None:
            result = self._predict_for_time(lot_id, horizon_minutes, at, live_fill)
            if result is not None:
                return result

        # Try XGBoost first
        if lot_id in self._xgb._models:
            df = _get_demand_df()
            lot_df = df[df["lot_id"] == lot_id] if "lot_id" in df.columns else df
            if len(lot_df) > 0:
                X, y, ts = build_features(lot_df, lot_id, max(1, horizon_minutes // 15))
                if len(X) > 0:
                    result = self._xgb.predict(lot_id, X[-1])
                    result["model"] = "XGBoost"
                    return result

        # Fallback: Moving Average
        ma_pred = float(self._ma.predict(lot_id))
        ma_pred = max(0.0, min(1.0, ma_pred))
        return {
            "fill_rate": ma_pred,
            "lower_90": max(0.0, ma_pred - 0.10),
            "upper_90": min(1.0, ma_pred + 0.10),
            "model": "MovingAverage",
        }

    def _slot_table(self, lot_id: str):
        """(X, weekday, hour, minute) for every usable row of this lot, cached."""
        cache = self.__dict__.setdefault("_slot_cache", {})
        if lot_id not in cache:
            import pandas as pd
            df = _get_demand_df()
            lot_df = df[df["lot_id"] == lot_id] if "lot_id" in df.columns else df
            X, _y, ts = build_features(lot_df, lot_id, 1)  # the models are trained for +15 min
            idx = pd.DatetimeIndex(ts)
            typical = lot_df.set_index("timestamp")["fill_rate"].reindex(idx).values  # fill at each row's time
            cache[lot_id] = (X, idx.dayofweek.values, idx.hour.values, idx.minute.values, typical)
        return cache[lot_id]

    def _slot_row(self, lot_id: str, when):
        """Index of the most recent synthetic row for the weekday / 15-min slot of `when`, else None."""
        X, dow, hour, minute, typical = self._slot_table(lot_id)
        slot_min = (when.minute // 15) * 15
        rows = ((dow == when.weekday()) & (hour == when.hour) & (minute == slot_min)).nonzero()[0]
        return int(rows[-1]) if len(rows) else None

    def _predict_for_time(self, lot_id: str, horizon_minutes: int, at, live_fill) -> Optional[Dict]:
        """Forecast for `at` + horizon from the synthetic row of the matching weekday/time slot."""
        if lot_id not in self._xgb._models:
            return None
        from datetime import timedelta
        # The model predicts +15 min from its input row, so the input row is `horizon - 15` ahead.
        row_time = at + timedelta(minutes=max(0, horizon_minutes - 15))
        i = self._slot_row(lot_id, row_time)
        if i is None:
            return None
        X, _dow, _hour, _minute, typical = self._slot_table(lot_id)
        result = self._xgb.predict(lot_id, X[i].copy())   # the model's time-of-day pattern
        result["model"] = "XGBoost"

        used_live = False
        if live_fill is not None:
            j = self._slot_row(lot_id, at)
            if j is not None and typical[j] == typical[j]:          # not NaN
                # Observed deviation from the typical level right now, carried forward with a decay
                # (half-life LIVE_HALF_LIFE_MIN). A heuristic: the model itself ignores its lag inputs.
                dev = float(live_fill) - float(typical[j])
                adj = dev * 0.5 ** (horizon_minutes / LIVE_HALF_LIFE_MIN)
                for key in ("fill_rate", "lower_90", "upper_90"):
                    result[key] = max(0.0, min(1.0, result[key] + adj))
                used_live = True
        days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        result["basis"] = {
            "mode": "time_of_day",
            "slot": f"{days[row_time.weekday()]} {row_time.hour:02d}:{(row_time.minute // 15) * 15:02d}",
            "live_fill_used": used_live,
        }
        return result

    def bind(self, at=None, live_fills: Optional[Dict[str, float]] = None) -> "BoundPredictor":
        """A view of this engine with a fixed time and live fills, same interface as the engine."""
        return BoundPredictor(self, at, live_fills or {})

    def predict_all(self, horizon_minutes: int = 15) -> Dict[str, Dict]:
        """Predict all lots at once."""
        return {lid: self.predict(lid, horizon_minutes) for lid in LOT_IDS}

    def get_forecast_snapshot(self, horizon_minutes: int = 15) -> Dict:
        """Return a forecast dict compatible with ParkingNavXFullStrategy.update_policy."""
        preds = self.predict_all(horizon_minutes)
        return {
            "lot_fill_rates": {lid: preds[lid]["fill_rate"] for lid in LOT_IDS},
            # Upper confidence bound — used by use_uncertainty=True path in P strategy
            "lot_fill_rates_upper": {lid: preds[lid].get("upper_90", preds[lid]["fill_rate"]) for lid in LOT_IDS},
            "horizon_minutes": horizon_minutes,
            "timestamp": time.time(),
        }


def get_predictor() -> PredictionEngine:
    """Singleton accessor — fits on first call."""
    global _PREDICTOR_SINGLETON
    if _PREDICTOR_SINGLETON is None:
        _PREDICTOR_SINGLETON = PredictionEngine()
        _PREDICTOR_SINGLETON.fit_all()
    return _PREDICTOR_SINGLETON


class BoundPredictor:
    """PredictionEngine with `at` / live fills fixed, so callers that only know predict()/predict_all()
    (risk engine, optimizer) get time-aware forecasts without any change."""

    def __init__(self, engine: PredictionEngine, at, live_fills: Dict[str, float]):
        self._e, self._at, self._live = engine, at, live_fills

    def predict(self, lot_id: str, horizon_minutes: int = 15) -> Dict:
        return self._e.predict(lot_id, horizon_minutes, at=self._at, live_fill=self._live.get(lot_id))

    def predict_all(self, horizon_minutes: int = 15) -> Dict[str, Dict]:
        return {lid: self.predict(lid, horizon_minutes) for lid in LOT_IDS}

    def get_forecast_snapshot(self, horizon_minutes: int = 15) -> Dict:
        preds = self.predict_all(horizon_minutes)
        return {
            "lot_fill_rates": {lid: preds[lid]["fill_rate"] for lid in LOT_IDS},
            "lot_fill_rates_upper": {lid: preds[lid].get("upper_90", preds[lid]["fill_rate"]) for lid in LOT_IDS},
            "horizon_minutes": horizon_minutes,
            "timestamp": time.time(),
        }


CAMPUS_TZ = "Asia/Kolkata"          # campus timezone (configs/campus/vitap.yaml)
LIVE_MAX_AGE_MIN = 30               # an occupancy reading older than this is not "live"


def campus_now():
    """Current campus-local wall-clock time as a naive datetime."""
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(CAMPUS_TZ)
    except Exception:
        tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(tz).replace(tzinfo=None)


def fresh_live_fills(conn) -> Dict[str, float]:
    """Latest recorded fill per lot, only if recorded within LIVE_MAX_AGE_MIN minutes."""
    out: Dict[str, float] = {}
    try:
        caps = {r[0]: r[1] for r in conn.execute(
            "SELECT parking_lot_id, usable_capacity FROM parking_lots WHERE campus_id='vitap'").fetchall()}
        for lot_id in LOT_IDS:
            row = conn.execute(
                """SELECT occupied_spaces, (julianday('now') - julianday(recorded_at)) * 1440.0
                   FROM lot_occupancy_history WHERE lot_id=? AND source NOT IN ('simulation', 'synthetic')
                   ORDER BY recorded_at DESC LIMIT 1""",
                (lot_id,)).fetchone()
            if row and row[1] is not None and row[1] <= LIVE_MAX_AGE_MIN and caps.get(lot_id, 0) > 0:
                out[lot_id] = min(1.0, row[0] / caps[lot_id])
    except Exception:
        pass
    return out


def forecast_context(conn, as_of=None):
    """(bound predictor, basis dict) for API use. `as_of` is an optional campus-local datetime/ISO string."""
    from datetime import datetime
    at = campus_now()
    if as_of:
        at = as_of if isinstance(as_of, datetime) else datetime.fromisoformat(str(as_of))
    live = {} if as_of else fresh_live_fills(conn)   # a what-if time must not mix in today's live data
    basis = {
        "mode": "time_of_day",
        "as_of": at.isoformat(timespec="minutes"),
        "timezone": CAMPUS_TZ,
        "live_lots": sorted(live),
        "data": data_description()["label"],
    }
    return get_predictor().bind(at=at, live_fills=live), basis
