"""FastAPI: the app to serve, and every route with its full path.

Routes are usually declared on an APIRouter with its own prefix, then mounted with
include_router(router, prefix=...), sometimes through several routers and with the prefix
held in a settings constant. This follows that chain to give each route its real path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.static.components import Component, owning_component
from wall_ai.understand.static.structure.facts import FileFacts

_PARSER = Parser(Language(tree_sitter_python.language()))
VERBS = {"get", "post", "put", "patch", "delete", "options", "head"}

Key = tuple[str, str]  # (file, variable)


@dataclass
class _Found:
    apps: list[Key] = field(default_factory=list)
    routers: dict[Key, str | None] = field(default_factory=dict)  # own prefix
    includes: list[tuple[Key, Key, str | None]] = field(default_factory=list)
    routes: list[tuple[Key, str, str, str, int]] = field(default_factory=list)


def add_fastapi(
    model: SystemModel, root: Path, components: list[Component], facts: dict[str, FileFacts]
) -> None:
    root = root.resolve()
    for comp in (c for c in components if c.language == "python"):
        files = {
            rel: f
            for rel, f in facts.items()
            if rel.endswith(".py") and owning_component(components, root / rel) == comp
        }
        found = _Found()
        sources = {rel: (root / rel).read_bytes() for rel in files}
        for rel, source in sources.items():
            _scan_file(found, rel, source, files[rel])
        if not found.apps and not found.routers:
            continue
        constants = _string_constants(sources)
        _add_routes(model, comp, found, constants)
        if found.apps:
            rel, var = sorted(found.apps, key=lambda k: (not k[0].endswith("main.py"), k))[0]
            module = PurePosixPath(rel).relative_to(comp.rel).with_suffix("")
            asgi_app = f"{'.'.join(module.parts)}:{var}"
            model.add_node(f"component:{comp.name}", "component", asgi_app=asgi_app)


def _scan_file(found: _Found, rel: str, source: bytes, facts: FileFacts) -> None:
    tree = _PARSER.parse(source)
    bindings = {imp.local: imp for imp in facts.imports if imp.local}

    def ref(node: Node | None) -> Key | None:
        if node is None:
            return None
        if node.type == "identifier":
            name = node.text.decode()
            imp = bindings.get(name)
            return (imp.file, imp.symbol) if imp and imp.file and imp.symbol else (rel, name)
        if node.type == "attribute":
            obj, attr = node.child_by_field_name("object"), node.child_by_field_name("attribute")
            imp = bindings.get(obj.text.decode())
            if imp and imp.file and imp.symbol is None:
                return (imp.file, attr.text.decode())
        return None

    for node in _module_level(tree.root_node):
        if node.type in ("assignment",):
            left, right = node.child_by_field_name("left"), node.child_by_field_name("right")
            if left is None or right is None or right.type != "call":
                continue
            kind = _last_name(right.child_by_field_name("function"))
            key = (rel, left.text.decode())
            if kind == "FastAPI":
                found.apps.append(key)
            elif kind == "APIRouter":
                found.routers[key] = _kwarg(right, "prefix") or ""
        elif node.type == "call":
            callee = node.child_by_field_name("function")
            if callee.type == "attribute" and _last_name(callee) == "include_router":
                args = node.child_by_field_name("arguments").named_children
                parent = ref(callee.child_by_field_name("object"))
                child = ref(args[0]) if args else None
                if parent and child:
                    found.includes.append((parent, child, _kwarg(node, "prefix")))
        elif node.type == "decorated_definition":
            definition = node.child_by_field_name("definition")
            if definition.type != "function_definition":
                continue
            handler = definition.child_by_field_name("name").text.decode()
            for decorator in (d for d in node.children if d.type == "decorator"):
                call = next((c for c in decorator.children if c.type == "call"), None)
                callee = call.child_by_field_name("function") if call else None
                if callee is None or callee.type != "attribute":
                    continue
                verb = _last_name(callee)
                path = _first_string(call)
                owner = ref(callee.child_by_field_name("object"))
                if verb in VERBS and path is not None and owner:
                    found.routes.append(
                        (owner, verb.upper(), path, handler, node.start_point.row + 1)
                    )


def _add_routes(model: SystemModel, comp: Component, found: _Found, constants) -> None:
    def resolve(prefix: str | None) -> str:
        if prefix is None:
            return ""
        if prefix.startswith("$"):  # a constant: settings.API_V1_STR -> API_V1_STR
            return constants.get(prefix[1:], "")
        return prefix

    def bases(key: Key, seen: frozenset) -> list[tuple[str, bool]]:
        """Path prefixes for routes on key, and whether it is mounted on an app."""
        if key in found.apps:
            return [("", True)]
        own = resolve(found.routers.get(key))
        parents = [(p, pre) for p, c, pre in found.includes if c == key and p not in seen]
        if not parents:
            return [(own, False)]
        return [
            (base + resolve(pre) + own, mounted)
            for parent, pre in parents
            for base, mounted in bases(parent, seen | {key})
        ]

    component_id = f"component:{comp.name}"
    for owner, method, path, handler, line in found.routes:
        for base, mounted in bases(owner, frozenset()):
            endpoint = f"endpoint:{comp.name}:{method} {base + path}"
            source = f"{owner[0]}:{line}"
            model.add_node(endpoint, "endpoint", method=method, path=base + path, mounted=mounted)
            model.add_edge(component_id, endpoint, "exposes", Evidence.STATIC, source)
            handler_id = f"function:{owner[0]}:{handler}"
            try:
                model.node(handler_id)
            except KeyError:
                continue
            model.add_edge(endpoint, handler_id, "handled_by", Evidence.STATIC, source)


def _module_level(root: Node):
    """Statements that run at import time, including inside if/try blocks, but not in defs."""
    for node in root.children:
        if node.type in ("function_definition", "class_definition"):
            continue
        if node.type == "expression_statement":
            yield from node.named_children
        elif node.type in ("if_statement", "try_statement", "else_clause", "elif_clause", "block"):
            yield from _module_level(node)
        else:
            yield node


def _kwarg(call: Node, name: str) -> str | None:
    """A keyword argument's value: the string itself, or "$NAME" for a constant like X.NAME."""
    for arg in call.child_by_field_name("arguments").named_children:
        if arg.type == "keyword_argument" and arg.child_by_field_name("name").text == name.encode():
            value = arg.child_by_field_name("value")
            if value.type == "string":
                return _string_value(value)
            if value.type in ("identifier", "attribute"):
                return f"${_last_name(value)}"
    return None


def _first_string(call: Node) -> str | None:
    for arg in call.child_by_field_name("arguments").named_children:
        if arg.type == "string":
            return _string_value(arg)
        if arg.type == "keyword_argument" and arg.child_by_field_name("name").text == b"path":
            value = arg.child_by_field_name("value")
            return _string_value(value) if value.type == "string" else None
    return None


def _string_constants(sources: dict[str, bytes]) -> dict[str, str]:
    """NAME -> value for string constants assigned exactly one value in the component."""
    pattern = re.compile(rb"^\s*([A-Za-z_]\w*)\s*(?::[^=\n]+)?=\s*[\"']([^\"'\n]*)[\"']\s*$", re.M)
    values: dict[str, set[str]] = {}
    for source in sources.values():
        for name, value in pattern.findall(source):
            values.setdefault(name.decode(), set()).add(value.decode())
    return {name: next(iter(v)) for name, v in values.items() if len(v) == 1}


def _string_value(node: Node) -> str | None:
    if any(c.type == "interpolation" for c in node.children):
        return None
    return "".join(c.text.decode() for c in node.children if c.type == "string_content")


def _last_name(node: Node | None) -> str | None:
    if node is None:
        return None
    if node.type == "identifier":
        return node.text.decode()
    if node.type == "attribute":
        return node.child_by_field_name("attribute").text.decode()
    return None
