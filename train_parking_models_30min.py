from pathlib import Path
import sys
import warnings

import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

warnings.filterwarnings("ignore")

DATA_PATH = Path("data/observations/vitap_observations.csv")
OUT_DIR = Path("outputs/parking_prediction")
OUT_DIR.mkdir(parents=True, exist_ok=True)

HORIZON_MINUTES = 30
TEST_FRACTION = 0.30
RANDOM_STATE = 42


def main():
    # --------------------------------------------------
    # 1. Load and validate the data
    # --------------------------------------------------
    if not DATA_PATH.exists():
        sys.exit(f"Dataset not found: {DATA_PATH}")

    df = pd.read_csv(DATA_PATH)

    required = {
        "timestamp", "parking_lot_id", "occupied_spaces",
        "capacity", "vehicle_count", "event_type", "event_intensity"
    }

    missing = required - set(df.columns)
    if missing:
        sys.exit(f"Missing required columns: {sorted(missing)}")

    df["timestamp"] = pd.to_datetime(
        df["timestamp"], utc=True, errors="coerce"
    )
    df = df.dropna(
        subset=["timestamp", "parking_lot_id", "occupied_spaces", "capacity"]
    ).copy()

    for col in ["occupied_spaces", "capacity",
                "vehicle_count", "event_intensity"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(
        subset=["occupied_spaces", "capacity"]
    )
    df = df[df["capacity"] > 0].copy()

    df = df.sort_values(
        ["parking_lot_id", "timestamp"]
    ).reset_index(drop=True)

    # Duplicate lot/timestamp records cannot define unique targets.
    duplicates = df.duplicated(
        ["parking_lot_id", "timestamp"]
    ).sum()

    if duplicates:
        print(f"Removing {duplicates} duplicate lot/timestamp records.")
        df = df.drop_duplicates(
            ["parking_lot_id", "timestamp"], keep="last"
        ).copy()

    # Keep ratios above 1: they may encode overflow conditions.
    df["occupancy_ratio"] = (
        df["occupied_spaces"] / df["capacity"]
    )

    print("\n=== DATA SUMMARY ===")
    print("Observations:", len(df))
    print("Parking lots:", df["parking_lot_id"].nunique())
    print("Missing values after basic cleaning:", int(df.isna().sum().sum()))
    print("Occupancy ratios above 1:", int((df["occupancy_ratio"] > 1).sum()))

    # --------------------------------------------------
    # 2. Create exact 15-minute targets
    # --------------------------------------------------
    future = df[
        ["parking_lot_id", "timestamp", "occupancy_ratio"]
    ].copy()

    future["timestamp"] -= pd.Timedelta(minutes=HORIZON_MINUTES)
    future = future.rename(
        columns={"occupancy_ratio": "target_30min"}
    )

    df = df.merge(
        future,
        on=["parking_lot_id", "timestamp"],
        how="left",
        validate="one_to_one"
    )

    df = df.dropna(subset=["target_30min"]).copy()

    if len(df) < 20:
        sys.exit(
            f"Only {len(df)} valid targets. "
            "Insufficient examples for this initial experiment."
        )

    # --------------------------------------------------
    # 3. Feature engineering
    # --------------------------------------------------
    df["hour"] = (
        df["timestamp"].dt.hour
        + df["timestamp"].dt.minute / 60
    )
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = (
        df["day_of_week"] >= 5
    ).astype(int)

    # Use only observed past values at exact elapsed times.
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
            validate="one_to_one"
        )

    # Current occupancy is known at prediction time.
    # Historical lags may be missing due to irregular timestamps.
    # Retain rows with missing lags; tree models can handle them
    # differently, so use explicit imputation for consistency.
    numeric_features = [
        "occupancy_ratio", "vehicle_count", "capacity",
        "event_intensity", "hour", "day_of_week", "is_weekend",
        "occupancy_lag_15m", "occupancy_lag_30m",
        "occupancy_lag_60m"
    ]

    categorical_features = ["parking_lot_id", "event_type"]

    for col in categorical_features:
        df[col] = df[col].fillna("unknown").astype(str)

    # --------------------------------------------------
    # 4. Chronological train/test split
    # --------------------------------------------------
    df = df.sort_values("timestamp").reset_index(drop=True)

    cutoff_index = int(len(df) * (1 - TEST_FRACTION))
    cutoff_time = df.iloc[cutoff_index]["timestamp"]

    train = df[df["timestamp"] < cutoff_time].copy()
    test = df[df["timestamp"] >= cutoff_time].copy()

    if len(train) < 10 or len(test) < 5:
        sys.exit("Train/test split too small. Inspect the dataset.")

    # Avoid a boundary timestamp appearing in both partitions.
    # The split is based on time, not random sampling.
    print("\n=== TRAIN / TEST SPLIT ===")
    print("Valid 30-minute targets:", len(df))
    print("Training rows:", len(train))
    print("Testing rows:", len(test))
    print("Cutoff:", cutoff_time)

    # One-hot encode categoricals and align columns.
    X_all = pd.get_dummies(
        df[numeric_features + categorical_features],
        columns=categorical_features,
        dtype=int
    )

    X_train = X_all.loc[train.index].copy()
    X_test = X_all.loc[test.index].copy()

    # Impute missing numerical features using training data only.
    for col in numeric_features:
        median_value = X_train[col].median()
        if pd.isna(median_value):
            median_value = 0
        X_train[col] = X_train[col].fillna(median_value)
        X_test[col] = X_test[col].fillna(median_value)

    y_train = train["target_30min"]
    y_test = test["target_30min"]

    # --------------------------------------------------
    # 5. Baseline and Random Forest
    # --------------------------------------------------
    predictions = {
        "Persistence baseline": test["occupancy_ratio"].to_numpy()
    }

    rf = RandomForestRegressor(
        n_estimators=200,
        max_depth=6,
        min_samples_split=4,
        random_state=RANDOM_STATE,
        n_jobs=-1
    )

    rf.fit(X_train, y_train)
    predictions["Random Forest"] = rf.predict(X_test)

    # --------------------------------------------------
    # 6. XGBoost
    # --------------------------------------------------
    try:
        from xgboost import XGBRegressor

        xgb = XGBRegressor(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=RANDOM_STATE,
            n_jobs=-1
        )

        xgb.fit(X_train, y_train)
        import joblib
        joblib.dump({"model": xgb, "feature_columns": list(X_train.columns)}, OUT_DIR / "xgboost_model_30min.joblib")
        print("XGBoost model saved")
        predictions["XGBoost"] = xgb.predict(X_test)

    except ImportError:
        print(
            "\nXGBoost is not installed. Install it with:\n"
            "python -m pip install xgboost\n"
            "Then rerun this script."
        )

    # --------------------------------------------------
    # 7. Evaluate models
    # --------------------------------------------------
    results = []

    actual = y_test.to_numpy()

    for name, pred in predictions.items():
        mae = mean_absolute_error(actual, pred)
        rmse = np.sqrt(mean_squared_error(actual, pred))

        results.append({
            "model": name,
            "MAE": mae,
            "RMSE": rmse,
            "test_rows": len(actual)
        })

    results_df = pd.DataFrame(results).sort_values("MAE")
    print("\n=== MODEL COMPARISON ===")
    print(results_df.to_string(index=False, float_format=lambda x: f"{x:.4f}"))

    # --------------------------------------------------
    # 8. Per-lot evaluation
    # --------------------------------------------------
    per_lot = []

    for lot, indices in test.groupby("parking_lot_id").groups.items():
        positions = test.index.get_indexer(indices)
        lot_actual = y_test.loc[indices].to_numpy()

        for name, pred in predictions.items():
            lot_pred = pred[positions]
            per_lot.append({
                "parking_lot_id": lot,
                "model": name,
                "MAE": mean_absolute_error(lot_actual, lot_pred),
                "test_rows": len(lot_actual)
            })

    per_lot_df = pd.DataFrame(per_lot)

    # --------------------------------------------------
    # 9. Save metrics and predictions
    # --------------------------------------------------
    results_df.to_csv(OUT_DIR / "model_comparison_30min.csv", index=False)
    per_lot_df.to_csv(OUT_DIR / "per_lot_metrics_30min.csv", index=False)

    prediction_df = test[
        ["timestamp", "parking_lot_id", "occupancy_ratio", "target_30min"]
    ].copy()

    prediction_df = prediction_df.rename(
        columns={
            "occupancy_ratio": "current_ratio",
            "target_30min": "actual_future_ratio"
        }
    )

    for name, pred in predictions.items():
        prediction_df[
            name.lower().replace(" ", "_") + "_prediction"
        ] = pred

    prediction_df.to_csv(
        OUT_DIR / "test_predictions_30min.csv", index=False
    )

    importance = pd.DataFrame({
        "feature": X_train.columns,
        "importance": rf.feature_importances_
    }).sort_values("importance", ascending=False)

    importance.to_csv(
        OUT_DIR / "random_forest_feature_importance_30min.csv",
        index=False
    )

    print("\n=== TOP RANDOM FOREST FEATURES ===")
    print(importance.head(10).to_string(index=False))

    print(f"\nSaved results to: {OUT_DIR.resolve()}")
    print("Original CSV was not modified.")
    print(
        "\nIMPORTANT: All results are preliminary experiments on "
        "synthetic data, not real-world validation."
    )


if __name__ == "__main__":
    main()
