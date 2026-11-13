"""Run logs — lists artefacts written by a completed simulation run."""
from pathlib import Path


def list_run_artifacts(run_dir: str | Path) -> list[str]:
    """Return sorted list of file paths inside a run output directory.

    Args:
        run_dir: Path to a run directory (e.g. runs/vitap-normal-day/...).

    Returns:
        Sorted list of relative filenames present in that directory.
    """
    p = Path(run_dir)
    if not p.exists():
        return []
    return sorted(f.name for f in p.iterdir() if f.is_file())


__all__ = ["list_run_artifacts"]
