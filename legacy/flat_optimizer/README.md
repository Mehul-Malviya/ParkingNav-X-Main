# legacy/flat_optimizer/ (archived, not part of the active test suite)

The original ParkingNav-X algorithmic core (Dijkstra routing + risk/cost
scoring + baseline comparisons), as received. Its modules import from an
`optimization.*` package path that was never actually present in this
flat checkout (`from optimization.constraints.gate_constraints import
is_gate_open`, etc.) — that mismatch predates this repo's reorganization
and is a pre-existing issue in the code as received, not something the
move caused.

`main.py` also reads its mock data from `data/mock/...`, but the actual
files live in `data/` directly (one level shallower) — same kind of
pre-existing path mismatch.

Its own tests are in `tests/`, run from inside this folder if needed —
they hit the same import issue.

How it worked: it starts from an entry gate, skips closed gates and full
lots, finds the shortest route to each available lot, then scores each
option as
`route cost × distance weight + congestion risk × congestion weight + overflow risk × overflow weight`
and recommends the lowest score.

See [../../docs/MEMBER1_SUBSYSTEM_REPORT.md](../../docs/MEMBER1_SUBSYSTEM_REPORT.md)
for the current, active system.
