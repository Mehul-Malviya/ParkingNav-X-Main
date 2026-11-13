import pandas as pd


class OccupancyFeatureExtractor:
    def __init__(self, data_path):
        self.data = pd.read_csv(data_path)

        self.data["observation_timestamp"] = pd.to_datetime(
            self.data["observation_timestamp"]
        )

        self.data = self.data.sort_values(
            ["parking_lot_id", "observation_timestamp"]
        ).copy()

        # Forward-fill occupancy values within each parking lot.
        self.data["occupancy_percentage"] = (
            self.data.groupby("parking_lot_id")["occupancy_percentage"]
            .ffill()
        )

        # If values are still missing at the beginning,
        # use 0 as the final fallback.
        self.data["occupancy_percentage"] = (
            self.data["occupancy_percentage"].fillna(0.0)
        )

    def extract(self, parking_lot_id, timestamp):
        timestamp = pd.to_datetime(timestamp)

        lot_data = self.data[
            self.data["parking_lot_id"] == parking_lot_id
        ].copy()

        if lot_data.empty:
            raise ValueError(
                f"No data found for parking lot: {parking_lot_id}"
            )

        lot_data = lot_data.sort_values("observation_timestamp").reset_index(
            drop=True
        )

        row = lot_data[
            lot_data["observation_timestamp"] == timestamp
        ]

        if row.empty:
            raise ValueError(
                f"No data found for {parking_lot_id} at {timestamp}"
            )

        position = row.index[0]

        # -------------------------
        # Temporal features
        # -------------------------

        features = {}

        # Normalize hour: 0-23 -> 0-1
        features["hour"] = timestamp.hour / 23.0

        # Normalize day: 0-6 -> 0-1
        features["day_of_week"] = timestamp.weekday() / 6.0

        # Weekend: False = 0, True = 1
        features["is_weekend"] = (
            1.0 if timestamp.weekday() >= 5 else 0.0
        )

        # VIT-AP currently has no configured academic events.
        features["academic_event"] = 0.0

        # No configured event multiplier currently.
        # 1.0 means normal demand.
        # Normalize roadmap range 0.05-1.50 to 0-1.
        event_multiplier = 1.0
        features["major_event_multiplier"] = (
            event_multiplier - 0.05
        ) / (1.50 - 0.05)

        # -------------------------
        # Historical lag features
        # -------------------------

        def get_lag(lag):
            if position >= lag:
                return float(
                    lot_data.iloc[position - lag]["occupancy_percentage"]
                )

            # Forward-filled early value
            return float(lot_data.iloc[0]["occupancy_percentage"])

        features["occupancy_t_minus_1"] = get_lag(1)
        features["occupancy_t_minus_2"] = get_lag(2)
        features["occupancy_t_minus_4"] = get_lag(4)
        features["occupancy_t_minus_96"] = get_lag(96)

        # Ensure all values are within 0-1.
        features = {
            key: max(0.0, min(1.0, value))
            for key, value in features.items()
        }

        return features
