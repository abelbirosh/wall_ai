"""Run the target in a sandbox and add what it did to the system model as observed links."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wall_ai.understand.model import SystemModel
from wall_ai.understand.runtime.ingest import ingest
from wall_ai.understand.runtime.sandbox import EphemeralSandbox, LimaSandbox
from wall_ai.understand.static.components import SKIP_DIRS, Component, is_test_file

INSIDE = Path(__file__).parent / "inside"
RUNS = Path.home() / ".wall_ai" / "runs"


def observe(
    model: SystemModel,
    root: Path,
    components: list[Component],
    sandbox: LimaSandbox | EphemeralSandbox,
    allow_hosts: tuple[str, ...] = (),
) -> dict:
    """Returns the run summary (run id, steps, where the raw output was kept)."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run:{stamp}"
    plan = build_plan(model, root, components, run_id, allow_hosts)
    out = RUNS / stamp
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "wallai-run"
        stage(root, plan, staging)
        sandbox.run(staging, out)
    summary = json.loads((out / "run.json").read_text())
    ingest(model, out, run_id)
    return {**summary, "out": str(out)}


def build_plan(
    model: SystemModel,
    root: Path,
    components: list[Component],
    run_id: str,
    allow_hosts: tuple[str, ...] = (),
) -> dict:
    root = root.resolve()
    planned = []
    for port, comp in enumerate((c for c in components if c.language == "python"), start=8000):
        component_id = f"component:{comp.name}"
        endpoints = sorted(
            {
                (model.node(e.dst).attrs["method"], model.node(e.dst).attrs["path"])
                for e in model.edges("exposes")
                if e.src == component_id
            }
        )
        tests = any(
            is_test_file(p.relative_to(root).as_posix())
            for p in comp.path.rglob("*.py")
            if not SKIP_DIRS.intersection(p.relative_to(root).parts)
        )
        planned.append(
            {
                "name": comp.name,
                "path": comp.rel,
                "requirements": "requirements.txt"
                if (comp.path / "requirements.txt").exists()
                else None,
                "asgi_app": model.node(component_id).attrs.get("asgi_app"),
                "port": port,
                "endpoints": [{"method": m, "path": p} for m, p in endpoints],
                "tests": tests,
            }
        )
    return {"run_id": run_id, "allow_hosts": list(allow_hosts), "components": planned}


def stage(root: Path, plan: dict, staging: Path) -> None:
    ignore = shutil.ignore_patterns(*SKIP_DIRS, ".*")
    shutil.copytree(root, staging / "target", ignore=ignore)
    shutil.copytree(INSIDE, staging / "inside", ignore=shutil.ignore_patterns("__pycache__"))
    (staging / "plan.json").write_text(json.dumps(plan, indent=2))
