"""Structure: files, functions, imports and calls, added to the system model."""

from __future__ import annotations

from pathlib import Path

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.static.components import (
    SKIP_DIRS,
    Component,
    is_test_file,
    owning_component,
)
from wall_ai.understand.static.structure import python, typescript
from wall_ai.understand.static.structure.facts import Call, FileFacts, Import

EXTRACTORS = {
    ".py": ("python", python.extract),
    ".ts": ("typescript", typescript.extract),
    ".tsx": ("typescript", typescript.extract),
    ".js": ("javascript", typescript.extract),
    ".jsx": ("javascript", typescript.extract),
}


def add_structure(model: SystemModel, root: Path, components: list[Component]) -> None:
    root = root.resolve()
    sources = {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"))
        if path.suffix in EXTRACTORS
        and path.is_file()
        and not SKIP_DIRS.intersection(path.relative_to(root).parts)
        and not is_test_file(path.relative_to(root).as_posix())
        and owning_component(components, path)
    }
    files = set(sources)

    all_facts: dict[str, FileFacts] = {}
    for rel, path in sources.items():
        component = owning_component(components, path)
        language, extract = EXTRACTORS[path.suffix]
        facts = extract(path.read_bytes(), rel, component.rel, files)
        all_facts[rel] = facts

        model.add_node(f"file:{rel}", "file", language=language, component=component.name)
        model.add_edge(
            f"component:{component.name}", f"file:{rel}", "contains", Evidence.STATIC, rel
        )
        for fn in facts.functions:
            fn_id = f"function:{rel}:{fn.name}"
            model.add_node(fn_id, "function", file=rel, name=fn.name, start=fn.start, end=fn.end)
            model.add_edge(f"file:{rel}", fn_id, "contains", Evidence.STATIC, f"{rel}:{fn.start}")

    for rel, facts in all_facts.items():
        bindings: dict[str, Import] = {}
        for imp in facts.imports:
            target = f"file:{imp.file}" if imp.file else imp.package
            if target and _has(model, target):
                model.add_edge(
                    f"file:{rel}", target, "imports", Evidence.STATIC, f"{rel}:{imp.line}"
                )
            if imp.local:
                bindings[imp.local] = imp

        local = {fn.name for fn in facts.functions}
        for call in facts.calls:
            callee = _resolve_call(call, rel, local, bindings)
            if callee and _has(model, callee):
                model.add_edge(
                    f"function:{rel}:{call.caller}",
                    callee,
                    "calls",
                    Evidence.STATIC,
                    f"{rel}:{call.line}",
                )


def _resolve_call(call: Call, rel: str, local: set[str], bindings: dict[str, Import]) -> str | None:
    *qualifier, name = call.target
    if not qualifier:
        if name in local:
            return f"function:{rel}:{name}"
        imp = bindings.get(name)
        if imp and imp.file and imp.symbol:
            return f"function:{imp.file}:{imp.symbol}"
        return None
    imp = bindings.get(".".join(qualifier))
    if imp and imp.file and imp.symbol is None:
        return f"function:{imp.file}:{name}"
    return None


def _has(model: SystemModel, node_id: str) -> bool:
    try:
        model.node(node_id)
    except KeyError:
        return False
    return True
