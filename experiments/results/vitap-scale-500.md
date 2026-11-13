# SCALE_500: Scalability run with 500 vehicles over 08:00-18:00.

`configs/scenarios/vitap/scale_500.yaml`, seeds 500-529, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/scale_500.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 500.0 ± 0.0 | 0.0 ± 0.0 | 33.8 ± 0.4 | 135.4 ± 1.4 | 1.1 ± 0.0 | 701.3 ± 6.5 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0058 ± 0.0002 |
| nearest_available | 0% | 30 | 500.0 ± 0.0 | 0.0 ± 0.0 | 33.8 ± 0.4 | 72.3 ± 0.3 | 1.0 ± 0.0 | 482.8 ± 6.7 | 94.8 ± 1.6 | 0.0 ± 0.0 | 0.0481 ± 0.0029 |
