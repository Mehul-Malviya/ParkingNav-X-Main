# LOT_CLOSURE: Morning rush with the academic lot closed.

`configs/scenarios/vitap/lot_closure.yaml`, seeds 300-329, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/lot_closure.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 400.0 ± 0.0 | 27.8 ± 0.1 | 766.7 ± 31.9 | 134.6 ± 1.3 | 1.0 ± 0.0 | 595.1 ± 10.1 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0091 ± 0.0016 |
| nearest_available | 0% | 30 | 400.0 ± 0.0 | 27.8 ± 0.1 | 766.7 ± 31.9 | 79.6 ± 0.2 | 1.0 ± 0.0 | 566.7 ± 8.8 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0442 ± 0.0013 |
