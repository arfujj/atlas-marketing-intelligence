"""Run registry: every analytical job writes to model_runs/{run_id}/ with a manifest.

A run id is `{kind}-{seed or tag}-{hash8}` where the hash covers the job's inputs and config,
so re-running the same job with the same inputs reproduces the same id. Manifests record the
git commit, seed, evidence type, inputs and wall-clock time, and every number quoted in the
docs cites one of these ids.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RUNS_DIR = Path(os.environ.get("ATLAS_RUNS_DIR", ROOT / "model_runs"))


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001 - git is optional (e.g. inside Docker)
        return None


def clean(o: Any) -> Any:
    """JSON-safe copy: NaN/inf → None, numpy scalars/arrays → Python, tuples → lists."""
    import math

    import numpy as np

    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def dump_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(clean(obj), indent=1, default=str, allow_nan=False))


def make_run_id(kind: str, tag: str | int, payload: dict[str, Any]) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f"{kind}-{tag}-{h[:8]}"


def run_dir(run_id: str, root: Path | None = None) -> Path:
    d = (root or RUNS_DIR) / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_manifest(run_id: str, kind: str, evidence_type: str, config: dict[str, Any],
                   outputs: dict[str, Any], root: Path | None = None,
                   started_at: datetime | None = None, **extra: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    manifest = {
        "run_id": run_id,
        "kind": kind,
        "evidence_type": evidence_type,
        "created_at": now.isoformat(timespec="seconds"),
        "wall_seconds": round((now - started_at).total_seconds(), 1) if started_at else None,
        "git_sha": _git_sha(),
        "config": config,
        "outputs": outputs,
        **extra,
    }
    (run_dir(run_id, root) / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str))
    return manifest


def read_manifest(run_id: str, root: Path | None = None) -> dict[str, Any]:
    return json.loads(((root or RUNS_DIR) / run_id / "manifest.json").read_text())


def latest_run(kind: str, root: Path | None = None, **match: Any) -> str | None:
    """Most recent run of `kind` whose config matches every key in `match`."""
    base = root or RUNS_DIR
    best: tuple[str, str] | None = None
    if not base.exists():
        return None
    for d in base.iterdir():
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        m = json.loads(mf.read_text())
        if m.get("kind") != kind:
            continue
        if any(m.get("config", {}).get(k) != v for k, v in match.items()):
            continue
        if best is None or m["created_at"] > best[0]:
            best = (m["created_at"], m["run_id"])
    return best[1] if best else None
