# legacy/

Archived code, kept for reference only. It is not part of the test suite
run from the repo root (`python -m pytest`).

## `flat_optimizer/`

The original ParkingNav-X algorithmic core: Dijkstra routing, congestion and
overflow-risk scoring, a weighted cost function, and baseline comparisons,
running on mock JSON data in `flat_optimizer/data/`.

As received, its modules import from an `optimization.*` package that never
existed in this repo, so it does not run without fixing those imports. See
[flat_optimizer/README.md](flat_optimizer/README.md).

The earlier `campus_twin_prototype/` was removed because `digital_twin/`
fully replaces it. It is still available in git history.
