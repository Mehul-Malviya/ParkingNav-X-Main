# Digital Twin Design — Member 1

**Owner:** Jyothi Reddy Pula (23BCE7882) · VIT-AP · ParkingNav-X

---

## What is a Digital Twin?

A Digital Twin is a live, stateful software model of a physical system that:
1. **Tracks state** — current occupancy, queue lengths, travel times
2. **Evolves over time** — state changes only through validated transitions
3. **Forks for what-if** — Member 3 clones the current state, simulates 15 min ahead, picks the best action
4. **Calibrates against observations** — parameters tuned from campus observations (currently synthetic; real gate-count data planned)

A dashboard only *shows* data. A Digital Twin *models* the system and supports look-ahead reasoning.

---

## Entity Model

| Entity | Key State Fields |
|--------|-----------------|
| ParkingLot | capacity, occupied, available, status, inflow/outflow last 5 min |
| Gate | service_rate, queue_length, avg_wait, status |
| Road | length, capacity, current_flow, travel_time (BPR), congestion_ratio, status |
| Vehicle | arrival_time, entry_gate, destination_zone, assigned_lot, state, complied |
| Event | type, demand_multiplier, affected_zones, start, duration, active |
| Campus | config_id, scenario_id, seed, sim_time, active_events, active_disruptions |

---

## State Transitions

State changes only via `twin.apply(transition)`. Each transition is:
- **Validated** (no occupancy > capacity, no parking in closed lot)
- **Logged** to an audit trail

Vehicle states: `ARRIVING → QUEUED_AT_GATE → IN_TRANSIT → SEARCHING → PARKED → DEPARTING → EXITED`  
If no lot available: `→ REJECTED`

---

## Snapshot / Fork

- `twin.snapshot()` → JSON dict (versioned schema `state_schema_version: "1.0"`)
- `Twin.from_snapshot(s)` → restore exact state
- `twin.fork()` → deep independent copy; mutation never affects parent

**Why fork matters:** Member 3 forks the twin, tests each candidate routing decision 15 min ahead, picks the one with least overflow — without touching the live state.

---

## Invariants (checked after every transition in debug mode)

- Occupied ≤ usable capacity for every lot
- Queue length ≥ 0 for every gate
- No vehicle in state PARKED in a closed lot
- Road flow ≥ 0
