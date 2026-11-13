# ROAD_CLOSURE: 

`configs/scenarios/vitap/road_closure.yaml`, seeds 9-38, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/road_closure.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 20.0 ± 0.0 | 100.0 ± 0.0 | 29.2 ± 0.8 | - | - | - | 0.0 ± 0.0 | 0.0 ± 0.0 | - |
| nearest_available | 0% | 30 | 20.0 ± 0.0 | 100.0 ± 0.0 | 29.2 ± 0.8 | - | - | - | 0.0 ± 0.0 | 0.0 ± 0.0 | - |
