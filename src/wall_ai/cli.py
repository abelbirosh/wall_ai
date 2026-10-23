"""wall-ai command line."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from wall_ai.understand.model import SystemModel
from wall_ai.understand.pipeline import understand


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="wall-ai")
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("understand", help="build the system model of a target")
    cmd.add_argument("target", type=Path)
    cmd.add_argument("-o", "--output", type=Path, help="write the model as JSON")
    args = parser.parse_args(argv)

    model = understand(args.target)
    if args.output:
        args.output.write_text(json.dumps(model.to_dict(), indent=2))
    print(summary(model))


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
