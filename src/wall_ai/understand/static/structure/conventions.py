"""Functions a framework or tool runs by convention, so nothing in the code calls them."""

from __future__ import annotations

import tomllib
from pathlib import Path


def entry_point(rel: str, name: str, decorators: list[str]) -> str | None:
    """Why a function runs without a visible caller, or None if it should have one."""
    if decorators:  # routes, validators, fixtures, tasks, properties: registered by decorator
        return f"decorator @{decorators[0]}"
    parts = rel.split("/")
    if "alembic" in parts and name in ("upgrade", "downgrade"):
        return "alembic migration"
    return None


def console_scripts(component_dir: Path, component_rel: str) -> list[tuple[str, str]]:
    """(file, function) pairs named in pyproject's [project.scripts], e.g. wall_ai.cli:main."""
    pyproject = component_dir / "pyproject.toml"
    if not pyproject.exists():
        return []
    try:
        scripts = tomllib.loads(pyproject.read_text()).get("project", {}).get("scripts", {})
    except tomllib.TOMLDecodeError:
        return []
    result = []
    for target in scripts.values():
        module, _, function = target.partition(":")
        path = module.replace(".", "/")
        base = "" if component_rel == "." else f"{component_rel}/"
        for candidate in (f"{base}{path}.py", f"{base}src/{path}.py", f"{base}{path}/__init__.py"):
            result.append((candidate, function.split(".")[0]))
    return result
