import pandas as pd
from sklearn.ensemble import RandomForestRegressor


class OccupancyPredictor:
    def __init__(self, data_path):
        self.data_path = data_path
        self.model = RandomForestRegressor(
            n_estimators=100,
            max_depth=15,
            min_samples_split=5,
            random_state=42,
        )

        self.data = pd.read_csv(data_path)

        self.data["observation_timestamp"] = pd.to_datetime(
            self.data["observation_timestamp"]
        )

        self.data = self.data.sort_values(
            ["parking_lot_id", "observation_timestamp"]
        ).reset_index(drop=True)

    def prepare_data(self, horizon=1):
        """Prepare chronological training and testing data."""

        feature_rows = []
        target_rows = []

        for parking_lot_id in self.data["parking_lot_id"].unique():

            lot_data = self.data[
                self.data["parking_lot_id"] == parking_lot_id
            ].copy()

            lot_data = lot_data.sort_values(
                "observation_timestamp"
            ).reset_index(drop=True)

            # We need at least 96 previous observations
            # to create the 24-hour lag.
            for i in range(96, len(lot_data) - horizon):

                timestamp = lot_data.iloc[i]["observation_timestamp"]

                features = {
                    "hour": timestamp.hour / 23.0,
                    "day_of_week": timestamp.weekday() / 6.0,
                    "is_weekend": (
                        1.0 if timestamp.weekday() >= 5 else 0.0
                    ),
                    "academic_event": 0.0,
                    "major_event_multiplier": (
                        1.0 - 0.05
                    ) / (1.50 - 0.05),

                    "occupancy_t_minus_1":
                        float(lot_data.iloc[i - 1]["occupancy_percentage"]),

                    "occupancy_t_minus_2":
                        float(lot_data.iloc[i - 2]["occupancy_percentage"]),

                    "occupancy_t_minus_4":
                        float(lot_data.iloc[i - 4]["occupancy_percentage"]),

                    "occupancy_t_minus_96":
                        float(lot_data.iloc[i - 96]["occupancy_percentage"]),
                }

                # Predict occupancy 30 minutes into the future.
                target = float(
                    lot_data.iloc[i + horizon]["occupancy_percentage"]
                )

                feature_rows.append(features)
                target_rows.append(target)

        X = pd.DataFrame(feature_rows)
        y = pd.Series(target_rows)

        # Chronological 70/30 split
        split_index = int(len(X) * 0.70)

        X_train = X.iloc[:split_index]
        X_test = X.iloc[split_index:]

        y_train = y.iloc[:split_index]
        y_test = y.iloc[split_index:]

        return X_train, X_test, y_train, y_test

    def train(self):
        """Train the Random Forest model."""

        X_train, X_test, y_train, y_test = self.prepare_data()

        self.model.fit(X_train, y_train)

        return X_train, X_test, y_train, y_test
    def evaluate(self, X_test, y_test):
        """Evaluate model performance on the test set."""

        from sklearn.metrics import (
            mean_absolute_error,
            mean_squared_error,
            mean_absolute_percentage_error,
        )
        import numpy as np

        predictions = self.model.predict(X_test)

        mae = mean_absolute_error(y_test, predictions)

        rmse = np.sqrt(
            mean_squared_error(y_test, predictions)
        )

        valid = y_test > 0.01

        mape = mean_absolute_percentage_error(
            y_test[valid],
            predictions[valid]
        )

        # Directional accuracy:
        # Did the prediction correctly identify whether
        # occupancy increased or decreased?
        actual_direction = np.sign(
            np.diff(y_test.values)
        )

        predicted_direction = np.sign(
            np.diff(predictions)
        )

        directional_accuracy = (
            np.mean(
                actual_direction == predicted_direction
            )
        )

        return {
            "MAE": mae,
            "RMSE": rmse,
            "MAPE": mape,
            "Directional Accuracy": directional_accuracy,
        }
    def baseline_predict(self, X_test):
        """Simple baseline: predict using the previous occupancy value."""

        return X_test["occupancy_t_minus_1"].values
