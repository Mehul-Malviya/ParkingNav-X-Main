# EVENT_DAY: Sports Festival (x1.5 demand, sports zone) on a normal 08:00-18:00 day.

`configs/scenarios/vitap/event_day.yaml`, seeds 200-229, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/event_day.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 669.0 ± 0.0 | 0.0 ± 0.0 | 36.0 ± 0.5 | 154.0 ± 1.9 | 1.2 ± 0.0 | 672.1 ± 7.7 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0057 ± 0.0002 |
| nearest_available | 0% | 30 | 669.0 ± 0.0 | 0.0 ± 0.0 | 36.0 ± 0.5 | 78.5 ± 0.7 | 1.0 ± 0.0 | 534.6 ± 7.1 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0445 ± 0.0013 |
