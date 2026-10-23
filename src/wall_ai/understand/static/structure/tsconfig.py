"""Read tsconfig path aliases ("@/*": ["./src/*"]) so aliased imports resolve to files."""

from __future__ import annotations

import json
import re
from pathlib import Path


def load_aliases(root: Path, component_dir: Path) -> list[tuple[str, str]]:
    """(prefix, replacement) pairs relative to the target root, e.g. ("@/", "frontend/src/")."""
    aliases: list[tuple[str, str]] = []
    for config in sorted(component_dir.glob("tsconfig*.json")):
        options = _options(config, depth=0)
        base = (config.parent / options.get("baseUrl", ".")).resolve()
        for pattern, targets in options.get("paths", {}).items():
            if not targets:
                continue
            wildcard = pattern.endswith("*")
            target = (base / targets[0].rstrip("*")).resolve()
            if not target.is_relative_to(root):
                continue
            rel = target.relative_to(root).as_posix()
            aliases.append((pattern[:-1], f"{rel}/") if wildcard else (pattern, rel))
    return sorted(set(aliases), key=lambda a: -len(a[0]))  # longest prefix first


def _options(config: Path, depth: int) -> dict:
    data = loads_lenient(config.read_text())
    options = {}
    parent = data.get("extends")
    if isinstance(parent, str) and parent.startswith(".") and depth < 5:
        parent_path = (config.parent / parent).resolve()
        if parent_path.suffix != ".json":
            parent_path = parent_path.with_suffix(".json")
        if parent_path.exists():
            options.update(_options(parent_path, depth + 1))
    options.update(data.get("compilerOptions", {}))
    return options


def loads_lenient(text: str) -> dict:
    """JSON with comments and trailing commas, as tsconfig allows."""
    out, i, in_string = [], 0, False
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1 : i + 2])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            i = text.find("\n", i)
            i = len(text) if i < 0 else i
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = len(text) if end < 0 else end + 2
            continue
        else:
            out.append(ch)
        i += 1
    try:
        return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))
    except ValueError:
        return {}
