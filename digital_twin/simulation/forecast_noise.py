"""
Forecast-noise injector for E5 robustness testing.

Perturbs Member 2's predictions before they reach the strategy:
  - adds Gaussian noise: pred' = pred × (1 + ε), ε ~ N(0, σ)
  - σ ∈ {0, 0.10, 0.20} tests graceful degradation
  - uses independent seed stream (never affects demand simulation)
  - widens prediction intervals consistently

Usage:
  injector = ForecastNoiseInjector(noise_level=0.10, seed=999)
  noisy_forecast = injector.perturb(forecast_dict)
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class ForecastNoiseInjector:
    """Injects Gaussian noise into occupancy predictions."""

    noise_level: float  # σ for N(0, σ); 0.0 = no noise, 0.10 = ±10%, 0.20 = ±20%
    seed: Optional[int] = None  # Independent seed stream (never affects arrivals)

    def __post_init__(self):
        """Initialize independent RNG for noise."""
        if self.seed is not None:
            self.rng = np.random.Generator(np.random.PCG64(self.seed))
        else:
            self.rng = np.random.Generator(np.random.PCG64())

        if not (0.0 <= self.noise_level <= 1.0):
            raise ValueError(f"noise_level must be in [0, 1]; got {self.noise_level}")

    def perturb(self, forecast: dict) -> dict:
        """
        Add Gaussian noise to occupancy predictions.

        Args:
            forecast: dict with keys like "occupancy_15min", "occupancy_30min",
                     "queue_length_gate_1", etc.

        Returns:
            perturbed copy with noise applied multiplicatively
        """
        if self.noise_level == 0.0:
            return forecast.copy()  # No-op

        noisy = {}
        for key, value in forecast.items():
            if isinstance(value, (int, float)) and key.startswith(("occupancy", "queue")):
                # Multiplicative noise: v' = v × (1 + ε), ε ~ N(0, σ)
                epsilon = self.rng.normal(loc=0.0, scale=self.noise_level)
                multiplier = 1.0 + epsilon
                # Clamp to [0, actual_max] to avoid negative occupancy
                noisy[key] = max(0.0, value * multiplier)
            else:
                noisy[key] = value

        return noisy

    def widen_intervals(self, forecast: dict, confidence: float = 0.95) -> dict:
        """
        Widen prediction intervals consistently.

        Args:
            forecast: dict with optional "_lower" and "_upper" keys
            confidence: confidence level (default 95% ≈ ±1.96σ)

        Returns:
            forecast with widened intervals
        """
        if self.noise_level == 0.0:
            return forecast.copy()

        # For 95% confidence, z = 1.96
        z = 1.96 if confidence == 0.95 else 1.645
        margin = self.noise_level * z

        widened = forecast.copy()
        for key, value in forecast.items():
            if isinstance(value, (int, float)):
                if key.endswith("_lower"):
                    widened[key] = max(0.0, value * (1.0 - margin))
                elif key.endswith("_upper"):
                    widened[key] = value * (1.0 + margin)

        return widened
