# GATE_CLOSURE: Morning rush with the visitor gate closed.

`configs/scenarios/vitap/gate_closure.yaml`, seeds 400-429, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/gate_closure.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 400.0 ± 0.0 | 0.0167 ± 0.0327 | 1737.9 ± 34.1 | 114.8 ± 0.6 | 1.1 ± 0.0 | 612.3 ± 7.4 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0056 ± 0.0002 |
| nearest_available | 0% | 30 | 400.0 ± 0.0 | 0.0083 ± 0.0163 | 1737.9 ± 34.1 | 111.7 ± 0.4 | 1.1 ± 0.0 | 607.7 ± 7.6 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0460 ± 0.0056 |
