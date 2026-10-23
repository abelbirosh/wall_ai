"""Structure: files, functions, imports, calls and references, added to the system model."""

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
from wall_ai.understand.static.structure.conventions import console_scripts, entry_point
from wall_ai.understand.static.structure.facts import MODULE, Call, Context, FileFacts, Import
from wall_ai.understand.static.structure.tsconfig import load_aliases

EXTRACTORS = {
    ".py": ("python", python.extract),
    ".ts": ("typescript", typescript.extract),
    ".tsx": ("typescript", typescript.extract),
    ".js": ("javascript", typescript.extract),
    ".jsx": ("javascript", typescript.extract),
}
SELF = {"self", "cls", "this"}


def add_structure(model: SystemModel, root: Path, components: list[Component]) -> dict:
    """Adds the structure and returns each file's facts for the analyzers that follow."""
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
    aliases = {c.name: load_aliases(root, c.path) for c in components if c.language == "js"}

    all_facts: dict[str, FileFacts] = {}
    for rel, path in sources.items():
        component = owning_component(components, path)
        language, extract = EXTRACTORS[path.suffix]
        ctx = Context(rel, component.rel, files, aliases.get(component.name, []))
        facts = all_facts[rel] = extract(path.read_bytes(), ctx)

        model.add_node(f"file:{rel}", "file", language=language, component=component.name)
        model.add_edge(
            f"component:{component.name}", f"file:{rel}", "contains", Evidence.STATIC, rel
        )
        for fn in facts.functions:
            fn_id = f"function:{rel}:{fn.name}"
            attrs = {"file": rel, "name": fn.name, "start": fn.start, "end": fn.end}
            if fn.decorators:
                attrs["decorators"] = fn.decorators
            if reason := entry_point(rel, fn.name, fn.decorators):
                attrs["entry_point"] = reason
            model.add_node(fn_id, "function", **attrs)
            model.add_edge(f"file:{rel}", fn_id, "contains", Evidence.STATIC, f"{rel}:{fn.start}")

    for comp in components:
        for file, function in console_scripts(comp.path, comp.rel):
            if _has(model, f"function:{file}:{function}"):
                model.add_node(f"function:{file}:{function}", "function", entry_point="script")

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
        for kind, items in (("calls", facts.calls), ("references", facts.references)):
            for call in items:
                callee = _resolve(call, rel, local, bindings, all_facts)
                caller = f"file:{rel}" if call.caller == MODULE else f"function:{rel}:{call.caller}"
                if callee and callee != caller and _has(model, callee):
                    model.add_edge(caller, callee, kind, Evidence.STATIC, f"{rel}:{call.line}")
    return all_facts


def _resolve(
    call: Call, rel: str, local: set[str], bindings: dict[str, Import], all_facts: dict
) -> str | None:
    *qualifier, name = call.target
    if not qualifier:
        if name in local:
            return f"function:{rel}:{name}"
        imp = bindings.get(name)
        if imp and imp.file and imp.symbol and imp.symbol != "default":
            file, symbol = _defining(imp.file, imp.symbol, all_facts)
            return f"function:{file}:{symbol}"
        return None
    if len(qualifier) == 1 and qualifier[0] in SELF and "." in call.caller:
        method = f"{call.caller.split('.')[0]}.{name}"  # self.x() inside Class.method
        return f"function:{rel}:{method}" if method in local else None
    if len(qualifier) == 1 and f"{qualifier[0]}.{name}" in local:  # Class.method() in its file
        return f"function:{rel}:{qualifier[0]}.{name}"
    imp = bindings.get(".".join(qualifier))
    if imp and imp.file and imp.symbol is None:  # module.function()
        return f"function:{imp.file}:{name}"
    if imp and imp.file and imp.symbol and len(qualifier) == 1:  # ImportedClass.method()
        file, symbol = _defining(imp.file, imp.symbol, all_facts)
        return f"function:{file}:{symbol}.{name}"
    return None


def _defining(file: str, symbol: str, all_facts: dict, depth: int = 0) -> tuple[str, str]:
    """Follow re-exports (barrel files) to the file that defines symbol."""
    facts = all_facts.get(file)
    if facts is None or depth > 5:
        return file, symbol
    if any(fn.name == symbol or fn.name.startswith(f"{symbol}.") for fn in facts.functions):
        return file, symbol
    for exported, original, target in facts.reexports:
        if exported == symbol:
            return _defining(target, original, all_facts, depth + 1)
    for exported, _, target in facts.reexports:
        if exported == "*":
            found = _defining(target, symbol, all_facts, depth + 1)
            if found != (target, symbol) or _defines(all_facts.get(target), symbol):
                return found
    return file, symbol


def _defines(facts, symbol: str) -> bool:
    return facts is not None and any(
        fn.name == symbol or fn.name.startswith(f"{symbol}.") for fn in facts.functions
    )


def _has(model: SystemModel, node_id: str) -> bool:
    try:
        model.node(node_id)
    except KeyError:
        return False
    return True
