# SCALE_1000: Scalability run with 1000 vehicles over 08:00-18:00.

`configs/scenarios/vitap/scale_1000.yaml`, seeds 1000-1029, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/scale_1000.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 1000.0 ± 0.0 | 0.7 ± 0.2 | 76.9 ± 11.2 | 167.9 ± 1.2 | 1.3 ± 0.0 | 635.2 ± 4.1 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0066 ± 0.0010 |
| nearest_available | 0% | 30 | 1000.0 ± 0.0 | 0.0333 ± 0.0534 | 76.9 ± 11.2 | 92.0 ± 0.7 | 1.1 ± 0.0 | 569.3 ± 4.7 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0410 ± 0.0013 |
