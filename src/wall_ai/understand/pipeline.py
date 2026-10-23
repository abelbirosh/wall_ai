"""Run the Understand pipelines against a target and return its system model."""

from __future__ import annotations

from pathlib import Path

from wall_ai.understand.model import SystemModel
from wall_ai.understand.static.components import find_components
from wall_ai.understand.static.integrations import add_integrations, run_semgrep
from wall_ai.understand.static.inventory import add_inventory, run_cdxgen
from wall_ai.understand.static.structure import add_structure


def understand(root: Path) -> SystemModel:
    model = SystemModel()
    components = find_components(root)
    for c in components:
        model.add_node(f"component:{c.name}", "component", language=c.language, path=c.rel)
    for c in components:
        add_inventory(model, c, run_cdxgen(c))
    add_structure(model, root, components)
    add_integrations(model, root, components, run_semgrep(root))
    return model
