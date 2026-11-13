# PEAK_HOUR: Morning rush, 400 vehicles in 2 hours, peaking at 08:30-09:00.

`configs/scenarios/vitap/peak_hour.yaml`, seeds 100-129, mean ± 95% CI. Demand is SYNTHETIC. Decision time is wall-clock; everything else is reproducible.
Regenerate: `python -m digital_twin.cli.run --scenario configs/scenarios/vitap/peak_hour.yaml --seeds 30 --strategy first_available nearest_available --forecast-error 0.0 0.1 0.2`

| Strategy | Forecast error | Seeds | Vehicles | Turned away (%) | Gate wait (s) | Time to park (s) | Lots tried | Walk to building (m) | Peak lot occupancy (%) | Capacity violations | Decision time (ms) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| first_available | 0% | 30 | 400.0 ± 0.0 | 0.8 ± 0.1 | 747.1 ± 44.0 | 136.5 ± 1.2 | 1.0 ± 0.0 | 594.8 ± 5.8 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0074 ± 0.0028 |
| first_available | 10% | 30 | 400.0 ± 0.0 | 4.2 ± 0.4 | 747.1 ± 44.0 | 244.7 ± 3.4 | 1.7 ± 0.0 | 597.2 ± 5.6 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0098 ± 0.0011 |
| first_available | 20% | 30 | 400.0 ± 0.0 | 3.7 ± 0.3 | 747.1 ± 44.0 | 245.2 ± 3.1 | 1.7 ± 0.0 | 598.0 ± 5.8 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0164 ± 0.0026 |
| nearest_available | 0% | 30 | 400.0 ± 0.0 | 0.8 ± 0.1 | 747.1 ± 44.0 | 83.3 ± 0.4 | 1.0 ± 0.0 | 608.7 ± 5.7 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0714 ± 0.0047 |
| nearest_available | 10% | 30 | 400.0 ± 0.0 | 0.8 ± 0.1 | 747.1 ± 44.0 | 122.5 ± 1.5 | 1.3 ± 0.0 | 607.8 ± 6.2 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0781 ± 0.0057 |
| nearest_available | 20% | 30 | 400.0 ± 0.0 | 0.9 ± 0.1 | 747.1 ± 44.0 | 120.9 ± 1.6 | 1.3 ± 0.0 | 607.7 ± 6.5 | 100.0 ± 0.0 | 0.0 ± 0.0 | 0.0780 ± 0.0047 |
