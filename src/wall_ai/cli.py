"""wall-ai command line."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from wall_ai.understand.model import SystemModel
from wall_ai.understand.pipeline import understand
from wall_ai.understand.runtime.ingest import not_executed
from wall_ai.understand.runtime.observe import observe
from wall_ai.understand.runtime.sandbox import default_sandbox
from wall_ai.understand.static.components import find_components

COMPARED = ("exposes", "handled_by", "calls", "talks_to")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wall-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("understand", help="build the system model of a target")
    cmd.add_argument("target", type=Path)
    cmd.add_argument("-o", "--output", type=Path, help="write the model as JSON")
    cmd.add_argument(
        "--run", action="store_true", help="also run the target in a sandbox and observe it"
    )
    cmd.add_argument(
        "--allow-host",
        action="append",
        default=[],
        help="let the target reach this host for real instead of getting a mock (repeatable)",
    )
    args = parser.parse_args(argv)

    model = understand(args.target)
    run = None
    if args.run:
        components = find_components(args.target)
        run = observe(model, args.target, components, default_sandbox(), tuple(args.allow_host))
    if args.output:
        args.output.write_text(json.dumps(model.to_dict(), indent=2))
    print(summary(model))
    if run:
        print(run_summary(model, run))


def summary(model: SystemModel) -> str:
    nodes = Counter(n.kind for n in model.nodes())
    edges = Counter(e.kind for e in model.edges())
    lines = [
        "nodes: " + ", ".join(f"{k}={v}" for k, v in sorted(nodes.items())),
        "links: " + ", ".join(f"{k}={v}" for k, v in sorted(edges.items())),
        "endpoints: " + ", ".join(sorted(n.id.split(":", 1)[1] for n in model.nodes("endpoint"))),
        "external hosts: " + ", ".join(sorted(n.id[5:] for n in model.nodes("host"))),
        "unused functions: " + ", ".join(sorted(n.id[9:] for n in model.unused_functions())),
    ]
    return "\n".join(lines)


def run_summary(model: SystemModel, run: dict) -> str:
    lines = [f"\nrun {run['run_id']} (raw output: {run['out']})"]
    for step in run["steps"]:
        mark = "ok" if step["ok"] else "FAILED"
        lines.append(f"  {mark:6} {step['name']}" + ("" if step["ok"] else f": {step['detail']}"))
    for kind in COMPARED:
        split = model.compare(kind)
        counts = ", ".join(f"{k}={len(v)}" for k, v in split.items())
        lines.append(f"{kind}: {counts}")
        for edge in split["observed_only"]:
            lines.append(f"  observed only: {edge.src} -> {edge.dst}")
    egress = {n.id[5:]: n.attrs["egress"] for n in model.nodes("host") if "egress" in n.attrs}
    lines.append(f"egress: {egress}")
    lines.append("never executed: " + ", ".join(sorted(n.id[9:] for n in not_executed(model))))
    return "\n".join(lines)
