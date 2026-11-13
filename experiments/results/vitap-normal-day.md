# NORMAL_DAY: 

`configs/scenarios/vitap/normal_day.yaml`, seeds 7-36, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/normal_day.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 60.0 ± 0.0 | 0.0 ± 0.0 | 29.8 ± 0.6 | 125.0 ± 3.3 | 1.0 ± 0.0 | 686.2 ± 21.3 | 37.5 ± 1.1 | 0.0 ± 0.0 | 0.0108 ± 0.0005 |
| nearest_available | 0% | 30 | 60.0 ± 0.0 | 0.0 ± 0.0 | 29.8 ± 0.6 | 72.0 ± 0.4 | 1.0 ± 0.0 | 482.7 ± 27.2 | 21.3 ± 0.8 | 0.0 ± 0.0 | 0.0480 ± 0.0024 |
