"""Inventory: which packages each component depends on, via cdxgen (CycloneDX SBOMs)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.static.components import Component

CDXGEN_TYPES = {"python": "python", "js": "js"}


def package_id(purl: str) -> str:
    """A purl without version, qualifiers or subpath: pkg:pypi/httpx@0.27.2 -> pkg:pypi/httpx."""
    base = purl.split("#", 1)[0].split("?", 1)[0]
    head, _, tail = base.partition("/")
    return f"{head}/{tail.rsplit('@', 1)[0]}" if "@" in tail else base


def run_cdxgen(component: Component) -> dict:
    cdxgen = shutil.which("cdxgen")
    if cdxgen is None:
        raise RuntimeError("cdxgen not found; install it with: npm install -g @cyclonedx/cdxgen")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "bom.json"
        # cdxgen prints an environment audit to stdout; capture it so it never reaches logs.
        subprocess.run(
            [cdxgen, "-t", CDXGEN_TYPES[component.language], "--no-recurse", "-o", str(out)]
            + [str(component.path)],
            check=True,
            capture_output=True,
        )
        return json.loads(out.read_text())


def add_inventory(model: SystemModel, component: Component, bom: dict) -> None:
    component_id = f"component:{component.name}"
    for item in bom.get("components", []):
        if "purl" in item:
            model.add_node(package_id(item["purl"]), "package", version=item.get("version"))

    root_ref = bom.get("metadata", {}).get("component", {}).get("bom-ref")
    graph = {d["ref"]: d.get("dependsOn", []) for d in bom.get("dependencies", [])}
    direct = graph.get(root_ref) or [i["purl"] for i in bom.get("components", []) if "purl" in i]
    source = f"cdxgen:{component.rel}"
    for purl in direct:
        model.add_edge(component_id, package_id(purl), "depends_on", Evidence.STATIC, source)
    known = {n.id for n in model.nodes("package")}
    for ref, deps in graph.items():
        if ref == root_ref or package_id(ref) not in known:
            continue
        for dep in deps:
            if package_id(dep) in known:
                model.add_edge(
                    package_id(ref), package_id(dep), "depends_on", Evidence.STATIC, source
                )
