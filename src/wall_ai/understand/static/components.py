"""Find the deployable components (services, packages) inside a target."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {"node_modules", ".venv", "venv", ".git", "dist", "build", "__pycache__"}
MANIFESTS = {
    "package.json": "js",
    "requirements.txt": "python",
    "pyproject.toml": "python",
}


@dataclass(frozen=True)
class Component:
    name: str
    path: Path  # absolute
    rel: str  # relative to the target root, "." for the root itself
    language: str


def find_components(root: Path) -> list[Component]:
    root = root.resolve()
    components = []
    for directory in _walk(root):
        for manifest, language in MANIFESTS.items():
            if (directory / manifest).is_file():
                rel = directory.relative_to(root).as_posix()
                name = directory.name if rel == "." else rel
                components.append(Component(name, directory, rel, language))
                break
    return components


def owning_component(components: list[Component], file: Path) -> Component | None:
    """The innermost component whose directory contains the file."""
    owners = [c for c in components if file.is_relative_to(c.path)]
    return max(owners, key=lambda c: len(c.path.parts), default=None)


def _walk(directory: Path):
    yield directory
    for child in sorted(directory.iterdir()):
        if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith("."):
            yield from _walk(child)
