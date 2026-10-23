"""Integrations: endpoints a target exposes and the hosts it calls, via Semgrep and wall_ai's
own rules (rules/integrations.yml)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.static.components import Component, owning_component

RULES = Path(__file__).parent / "rules" / "integrations.yml"


def run_semgrep(root: Path) -> list[dict]:
    semgrep = shutil.which("semgrep")
    if semgrep is None:
        raise RuntimeError("semgrep not found; install it with: uv tool install semgrep")
    result = subprocess.run(
        [semgrep, "scan", "--config", str(RULES), "--json", "--metrics=off", "--quiet", "."],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)["results"]


def add_integrations(
    model: SystemModel, root: Path, components: list[Component], results: list[dict]
) -> None:
    root = root.resolve()
    rule = lambda r: r["check_id"].rsplit(".rules.", 1)[-1]  # noqa: E731
    routes = [r for r in results if rule(r).startswith("route.")]
    calls = [r for r in results if rule(r).startswith("http.")]

    for r in routes:
        component = owning_component(components, root / r["path"])
        method, path, *func = r["extra"]["message"].split(" ")
        method = method.upper()
        endpoint = f"endpoint:{component.name}:{method} {path}"
        source = f"{r['path']}:{r['start']['line']}"
        model.add_node(endpoint, "endpoint", method=method, path=path)
        model.add_edge(f"component:{component.name}", endpoint, "exposes", Evidence.STATIC, source)
        handler = func[0] if func else f"<{method} {path}>"
        if len(func) > 1:  # FastAPI: record the ASGI app so the runtime pipeline can serve it
            module = Path(r["path"]).relative_to(component.rel).with_suffix("")
            asgi_app = f"{'.'.join(module.parts)}:{func[1]}"
            model.add_node(f"component:{component.name}", "component", asgi_app=asgi_app)
        handler_id = f"function:{r['path']}:{handler}"
        if any(n.id == handler_id for n in model.nodes("function")):
            model.add_edge(endpoint, handler_id, "handled_by", Evidence.STATIC, source)

    names = {c.name for c in components}
    for r in calls:
        verb, url = r["extra"]["message"].split(" ", 1)
        method = "GET" if verb == "fetch" else verb.upper()
        parsed = urlparse(url)
        if not parsed.hostname:
            continue
        line = r["start"]["line"]
        caller = _enclosing_function(model, r["path"], line) or f"file:{r['path']}"
        if parsed.hostname in names:
            endpoint = f"endpoint:{parsed.hostname}:{method} {parsed.path or '/'}"
            known = any(n.id == endpoint for n in model.nodes("endpoint"))
            target = endpoint if known else f"component:{parsed.hostname}"
        else:
            target = f"host:{parsed.hostname}"
            model.add_node(target, "host")
        model.add_edge(caller, target, "talks_to", Evidence.STATIC, f"{r['path']}:{line}")


def _enclosing_function(model: SystemModel, path: str, line: int) -> str | None:
    """The innermost function in the file whose span contains the line."""
    spans = [
        n
        for n in model.nodes("function")
        if n.attrs["file"] == path and n.attrs["start"] <= line <= n.attrs["end"]
    ]
    best = min(spans, key=lambda n: n.attrs["end"] - n.attrs["start"], default=None)
    return best.id if best else None
