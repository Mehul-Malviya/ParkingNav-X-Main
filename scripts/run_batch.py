"""
Run VIT-AP scenarios x strategies x seeds and write runs/<scenario_id>/<strategy>/seed_N/.

Usage:
    python scripts/run_batch.py --scenarios E1_normal_day,E2_event_placement --seeds 0-29
    python scripts/run_batch.py --scenarios all --seeds 0-29 --strategies B1,B2

Then regenerate the table:  python scripts/generate_results_summary.py
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from digital_twin.config_loader import load_campus_config  # noqa: E402
from digital_twin.db import apply_migrations, get_connection  # noqa: E402
from digital_twin.simulation.engine import SimulationEngine  # noqa: E402
from digital_twin.simulation.scenario import ScenarioLoader  # noqa: E402
from digital_twin.simulation.demo_strategies import (  # noqa: E402
    ParkingNavXFullStrategy,
    PredictionOnlyStrategy,
)
from digital_twin.simulation.strategy import (  # noqa: E402
    FirstAvailableStrategy,
    NearestAvailableStrategy,
)

SCENARIO_DIR = ROOT / "configs" / "scenarios" / "vitap"
CAMPUS_YAML = ROOT / "configs" / "campus" / "vitap.yaml"
STRATEGIES = {
    "B1": FirstAvailableStrategy,
    "B2": NearestAvailableStrategy,
    "B3": PredictionOnlyStrategy,
    "P":  ParkingNavXFullStrategy,
}


def parse_seeds(text: str) -> list[int]:
    if "-" in text and "," not in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in text.split(",")]


def _run_one(job):
    stem, strat, seed = job
    conn = get_connection(":memory:")
    apply_migrations(conn)
    load_campus_config(CAMPUS_YAML, conn)
    scenario = ScenarioLoader.load(SCENARIO_DIR / f"{stem}.yaml")
    scenario.random_seed = seed
    SimulationEngine().run(scenario, STRATEGIES[strat](), conn)
    return job


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", required=True, help="Comma-separated scenario file stems, or 'all'")
    ap.add_argument("--seeds", default="0-29", help="e.g. 0-29 or 0,5,9")
    ap.add_argument("--strategies", default="B1,B2", help="any of B1,B2,B3,P")
    ap.add_argument("--jobs", type=int, default=1, help="parallel worker processes (each run is independent and seeded)")
    args = ap.parse_args()

    if args.scenarios == "all":
        stems = sorted(p.stem for p in SCENARIO_DIR.glob("*.yaml"))
    else:
        stems = [s.strip() for s in args.scenarios.split(",")]
    strategies = [s.strip().upper() for s in args.strategies.split(",")]
    for s in strategies:
        if s not in STRATEGIES:
            sys.exit(f"Unknown strategy '{s}'. Choose from: {', '.join(STRATEGIES)}")
    for stem in stems:
        if not (SCENARIO_DIR / f"{stem}.yaml").exists():
            sys.exit(f"Scenario file not found: {SCENARIO_DIR / (stem + '.yaml')}")
    seeds = parse_seeds(args.seeds)

    jobs = [(stem, strat, seed) for stem in stems for strat in strategies for seed in seeds]
    done = 0
    if args.jobs <= 1:
        results = map(_run_one, jobs)
    else:
        from concurrent.futures import ProcessPoolExecutor
        pool = ProcessPoolExecutor(max_workers=args.jobs)
        results = pool.map(_run_one, jobs)
    for stem, strat, seed in results:
        done += 1
        if done % 20 == 0 or done == len(jobs):
            print(f"{done}/{len(jobs)} runs done (last: {stem} {strat} seed {seed})", flush=True)


if __name__ == "__main__":
    main()
