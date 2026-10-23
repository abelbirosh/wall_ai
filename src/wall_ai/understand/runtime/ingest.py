"""Turn what the sandbox recorded into observed links on the system model.

Reads <out>/<component>/<process>/{spans-*.jsonl, calls-*.json} and <out>/egress.jsonl.
IDs match the static pipeline, so observed links land on the same nodes.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from wall_ai.understand.model import Evidence, Node, SystemModel

LOOPBACK = {"localhost", "127.0.0.1", "::1", "testserver"}


def ingest(model: SystemModel, out: Path, run_id: str) -> None:
    executed: Counter = Counter()
    for component_dir in sorted(p for p in out.iterdir() if p.is_dir()):
        component = component_dir.name
        for calls_file in sorted(component_dir.glob("*/calls-*.json")):
            data = json.loads(calls_file.read_text())
            executed.update(data["functions"])
            for caller, callee, count in data["calls"]:
                src, dst = _function(model, caller), _function(model, callee)
                if src and dst:
                    model.add_edge(src, dst, "calls", Evidence.OBSERVED, run_id, count=count)
        spans = [
            json.loads(line)
            for spans_file in sorted(component_dir.glob("*/spans-*.jsonl"))
            for line in spans_file.read_text().splitlines()
            if line
        ]
        _ingest_server_spans(model, component, spans, run_id)
        _ingest_client_spans(model, spans, run_id)

    for function, count in executed.items():
        if node_id := _function(model, function):
            model.add_node(node_id, "function", executed=count)
    for edge in model.edges("handled_by"):
        exposes = [e for e in model.edges("exposes") if e.dst == edge.src]
        endpoint_seen = any(Evidence.OBSERVED in e.evidence for e in exposes)
        if endpoint_seen and model.node(edge.dst).attrs.get("executed"):
            model.add_edge(edge.src, edge.dst, "handled_by", Evidence.OBSERVED, run_id)

    _ingest_egress(model, out / "egress.jsonl")


def not_executed(model: SystemModel) -> list[Node]:
    """Functions the code defines that never ran."""
    return [
        n
        for n in model.nodes("function")
        if not n.attrs.get("executed") and not n.attrs.get("observed_only")
    ]


def _ingest_server_spans(model, component, spans, run_id) -> None:
    hits: Counter = Counter()
    for span in spans:
        attrs = span["attributes"]
        route = attrs.get("http.route")
        method = attrs.get("http.request.method") or attrs.get("http.method")
        if span["kind"] == "SERVER" and route and method:
            hits[f"endpoint:{component}:{method} {route}"] += 1
    for endpoint, count in hits.items():
        method, path = endpoint.split(":", 2)[2].split(" ", 1)
        model.add_node(endpoint, "endpoint", method=method, path=path)
        model.add_edge(
            f"component:{component}", endpoint, "exposes", Evidence.OBSERVED, run_id, count=count
        )


def _ingest_client_spans(model, spans, run_id) -> None:
    components = {n.id.split(":", 1)[1] for n in model.nodes("component")}
    for span in spans:
        attrs = span["attributes"]
        url = urlparse(attrs.get("url.full") or attrs.get("http.url") or "")
        caller = _function(model, attrs.get("wallai.caller", ""))
        if span["kind"] != "CLIENT" or not url.hostname or url.hostname in LOOPBACK or not caller:
            continue
        if url.hostname in components:
            method = attrs.get("http.request.method") or attrs.get("http.method") or "GET"
            target = f"endpoint:{url.hostname}:{method} {url.path or '/'}"
            if not _has(model, target):
                target = f"component:{url.hostname}"
        else:
            target = f"host:{url.hostname}"
            model.add_node(target, "host")
        model.add_edge(caller, target, "talks_to", Evidence.OBSERVED, run_id, count=1)


def _ingest_egress(model: SystemModel, log: Path) -> None:
    if not log.exists():
        return
    actions: dict[str, Counter] = {}
    for line in log.read_text().splitlines():
        record = json.loads(line)
        if record.get("host"):
            actions.setdefault(record["host"], Counter())[record["action"]] += 1
    for host, counts in actions.items():
        model.add_node(f"host:{host}", "host", egress=dict(counts))


def _function(model: SystemModel, recorded: str) -> str | None:
    """Map a recorded 'path:qualname' to a function node, adding one the static side missed."""
    if ":" not in recorded:
        return None
    path, _ = recorded.split(":", 1)
    node_id = f"function:{recorded}"
    if _has(model, node_id):
        return node_id
    if not _has(model, f"file:{path}"):
        return None
    model.add_node(node_id, "function", file=path, observed_only=True)
    model.add_edge(f"file:{path}", node_id, "contains", Evidence.OBSERVED, "runtime")
    return node_id


def _has(model: SystemModel, node_id: str) -> bool:
    try:
        model.node(node_id)
    except KeyError:
        return False
    return True
