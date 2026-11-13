
from pathlib import Path
import json
import sys

import joblib
import numpy as np
import pandas as pd

DATA_PATH = Path("data/observations/vitap_observations.csv")
MODEL_PATH = Path("outputs/parking_prediction/xgboost_model.joblib")
OUT_DIR = Path("outputs/optimizer_inputs")

NUMERIC_FEATURES = [
    "occupancy_ratio",
    "vehicle_count",
    "capacity",
    "event_intensity",
    "hour",
    "day_of_week",
    "is_weekend",
    "occupancy_lag_15m",
    "occupancy_lag_30m",
    "occupancy_lag_60m",
]
CATEGORICAL_FEATURES = ["parking_lot_id", "event_type"]


def fail(message):
    sys.exit(f"ERROR: {message}")


def main():
    if not DATA_PATH.exists():
        fail(f"Dataset not found: {DATA_PATH}")
    if not MODEL_PATH.exists():
        fail(f"Model not found: {MODEL_PATH}")

    bundle = joblib.load(MODEL_PATH)
    model = bundle["model"]
    feature_columns = bundle["feature_columns"]

    df = pd.read_csv(DATA_PATH)

    required = {
        "timestamp", "parking_lot_id", "occupied_spaces",
        "capacity", "vehicle_count", "event_type", "event_intensity",
    }
    missing = required - set(df.columns)
    if missing:
        fail(f"Missing dataset columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )

    for col in [
        "occupied_spaces", "capacity",
        "vehicle_count", "event_intensity",
    ]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(
        subset=[
            "timestamp", "parking_lot_id",
            "occupied_spaces", "capacity",
        ]
    ).copy()
    df = df[df["capacity"] > 0].copy()
    df = df.sort_values(
        ["parking_lot_id", "timestamp"]
    ).drop_duplicates(
        ["parking_lot_id", "timestamp"], keep="last"
    ).copy()

    if df.empty:
        fail("No valid observations remain after cleaning.")

    df["parking_lot_id"] = df["parking_lot_id"].astype(str)
    df["event_type"] = df["event_type"].fillna("unknown").astype(str)
    df["occupancy_ratio"] = df["occupied_spaces"] / df["capacity"]

    # Recreate the training features.
    df["hour"] = (
        df["timestamp"].dt.hour
        + df["timestamp"].dt.minute / 60
    )
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)

    history = df[
        ["parking_lot_id", "timestamp", "occupancy_ratio"]
    ].copy()

    for lag in [15, 30, 60]:
        lookup = history.copy()
        lookup["timestamp"] += pd.Timedelta(minutes=lag)
        lookup = lookup.rename(
            columns={"occupancy_ratio": f"occupancy_lag_{lag}m"}
        )
        df = df.merge(
            lookup,
            on=["parking_lot_id", "timestamp"],
            how="left",
            validate="one_to_one",
        )

    # Recreate the original training medians using the same valid-target
    # population and chronological training split.
    future = df[
        ["parking_lot_id", "timestamp", "occupancy_ratio"]
    ].copy()
    future["timestamp"] -= pd.Timedelta(minutes=15)
    future = future.rename(
        columns={"occupancy_ratio": "target_15min"}
    )
    target_df = df.merge(
        future,
        on=["parking_lot_id", "timestamp"],
        how="left",
        validate="one_to_one",
    ).dropna(subset=["target_15min"]).copy()

    if target_df.empty:
        fail("Could not reconstruct training rows with 15-minute targets.")

    target_df = target_df.sort_values("timestamp").reset_index(drop=True)
    cutoff_index = int(len(target_df) * 0.70)
    if cutoff_index <= 0:
        fail("Not enough valid targets to reconstruct training medians.")

    train = target_df.iloc[:cutoff_index].copy()
    medians = {}
    for col in NUMERIC_FEATURES:
        value = train[col].median()
        medians[col] = 0.0 if pd.isna(value) else float(value)

    # Use the latest observation for each lot.
    latest = (
        df.sort_values("timestamp")
        .groupby("parking_lot_id", as_index=False)
        .tail(1)
        .copy()
    )

    # Categories must match the model's training columns.
    trained_lots = {
        col[len("parking_lot_id_"):]
        for col in feature_columns
        if col.startswith("parking_lot_id_")
    }
    unseen_lots = sorted(set(latest["parking_lot_id"]) - trained_lots)
    if unseen_lots:
        fail(
            "These lots were not represented in the saved model's "
            f"training features: {unseen_lots}. Retrain with those lots "
            "included before generating forecasts."
        )

    X = pd.get_dummies(
        latest[NUMERIC_FEATURES + CATEGORICAL_FEATURES],
        columns=CATEGORICAL_FEATURES,
        dtype=int,
    )

    for col in NUMERIC_FEATURES:
        X[col] = X[col].fillna(medians[col])

    # Missing training categories become zero; extra categories are ignored
    # only after checking that parking lots were seen during training.
    X = X.reindex(columns=feature_columns, fill_value=0)

    if not np.isfinite(X.to_numpy(dtype=float)).all():
        fail("Model features contain non-finite values.")

    predictions = np.asarray(model.predict(X), dtype=float)
    if not np.isfinite(predictions).all():
        fail("Model returned non-finite predictions.")

    # Preserve overflow forecasts above capacity; do not cap ratios at 1.
    latest = latest.reset_index(drop=True)
    forecast = pd.DataFrame({
        "parking_lot_id": latest["parking_lot_id"],
        "source_timestamp": latest["timestamp"].astype(str),
        "forecast_timestamp": (
            latest["timestamp"] + pd.Timedelta(minutes=15)
        ).astype(str),
        "capacity": latest["capacity"].astype(float),
        "current_occupancy_ratio": latest["occupancy_ratio"].astype(float),
        "predicted_occupancy_ratio": predictions,
    })
    forecast["predicted_occupied_spaces"] = (
        forecast["predicted_occupancy_ratio"] * forecast["capacity"]
    ).round(2)
    forecast["predicted_available_spaces"] = (
        forecast["capacity"] - forecast["predicted_occupied_spaces"]
    ).round(2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / "parking_occupancy_forecasts.csv"
    json_path = OUT_DIR / "parking_occupancy_forecasts.json"

    forecast.to_csv(csv_path, index=False)

    payload = {
        "forecast_horizon_minutes": 15,
        "source": "XGBoost occupancy model",
        "note": (
            "Preliminary forecasts from synthetic observations. "
            "Occupancy ratios above 1 are retained to represent overflow. "
            "Available spaces may be negative when overflow is predicted. "
            "These are parking forecasts, not road congestion predictions."
        ),
        "parking_lots": forecast.to_dict(orient="records"),
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, allow_nan=False)

    # Output checks.
    assert forecast["parking_lot_id"].is_unique
    assert forecast["capacity"].gt(0).all()
    assert np.isfinite(
        forecast.select_dtypes(include=[np.number]).to_numpy()
    ).all()
    assert (forecast["forecast_timestamp"] ==
            (pd.to_datetime(forecast["source_timestamp"], utc=True)
             + pd.Timedelta(minutes=15)).astype(str)).all()

    print("\nOptimizer input preparation successful.")
    print("Parking lots forecast:", len(forecast))
    print("CSV:", csv_path)
    print("JSON:", json_path)
    print("\nForecast preview:")
    print(forecast.to_string(index=False))
    print(
        "\nNote: road congestion predictions remain separate; "
        "the optimiser has not been modified or run."
    )


if __name__ == "__main__":
    main()
