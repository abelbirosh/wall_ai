"""Extract functions, imports and calls from TypeScript/JavaScript source with tree-sitter."""

from __future__ import annotations

import posixpath

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from wall_ai.understand.static.structure.facts import Call, FileFacts, Function, Import

_TS = Parser(Language(tree_sitter_typescript.language_typescript()))
_TSX = Parser(Language(tree_sitter_typescript.language_tsx()))

HTTP_VERBS = {"get", "post", "put", "patch", "delete"}
FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}
EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def extract(source: bytes, rel_path: str, component_rel: str, files: set[str]) -> FileFacts:
    parser = _TSX if rel_path.endswith((".tsx", ".jsx")) else _TS
    facts = FileFacts()
    tree = parser.parse(source)  # keep the tree alive while its nodes are in use
    for node in tree.root_node.children:
        if node.type == "export_statement" and node.child_by_field_name("declaration"):
            node = node.child_by_field_name("declaration")
        if node.type == "function_declaration":
            _add_function(facts, node, _text(node.child_by_field_name("name")))
        elif node.type in ("lexical_declaration", "variable_declaration"):
            for declarator in node.named_children:
                value = declarator.child_by_field_name("value")
                if value is not None and value.type in FUNCTION_VALUES:
                    _add_function(facts, value, _text(declarator.child_by_field_name("name")))
        elif node.type == "expression_statement":
            _add_route_handler(facts, node.named_children[0])
        elif node.type == "import_statement":
            facts.imports.extend(_imports(node, rel_path, files))
    return facts


def _add_route_handler(facts: FileFacts, call: Node) -> None:
    """Name inline handlers like app.post("/notify", async () => ...) as <POST /notify>."""
    if call.type != "call_expression":
        return
    callee = call.child_by_field_name("function")
    if callee.type != "member_expression":
        return
    verb = _text(callee.child_by_field_name("property"))
    args = call.child_by_field_name("arguments").named_children
    if verb not in HTTP_VERBS or not args or args[0].type != "string":
        return
    handler = next((a for a in reversed(args) if a.type in FUNCTION_VALUES), None)
    if handler is not None:
        _add_function(facts, handler, f"<{verb.upper()} {_string(args[0])}>")


def _add_function(facts: FileFacts, node: Node, name: str) -> None:
    facts.functions.append(Function(name, node.start_point.row + 1, node.end_point.row + 1))
    for call in _descendants(node.child_by_field_name("body") or node, "call_expression"):
        target = _dotted(call.child_by_field_name("function"))
        if target:
            facts.calls.append(Call(name, target, call.start_point.row + 1))


def _imports(node: Node, rel_path: str, files: set[str]) -> list[Import]:
    line = node.start_point.row + 1
    spec = _string(node.child_by_field_name("source"))
    file = _resolve(spec, rel_path, files) if spec.startswith(".") else None
    package = None if file or spec.startswith(".") else _package(spec)
    clause = next((c for c in node.named_children if c.type == "import_clause"), None)
    if clause is None:
        return [Import(None, file, package, None, line)]
    result = []
    for part in clause.named_children:
        if part.type == "identifier":
            result.append(Import(_text(part), file, package, "default", line))
        elif part.type == "namespace_import":
            result.append(Import(_text(part.named_children[0]), file, package, None, line))
        elif part.type == "named_imports":
            for spec_node in part.named_children:
                name = _text(spec_node.child_by_field_name("name"))
                alias = spec_node.child_by_field_name("alias")
                result.append(Import(_text(alias) if alias else name, file, package, name, line))
    return result


def _resolve(spec: str, rel_path: str, files: set[str]) -> str | None:
    base = posixpath.normpath(posixpath.join(posixpath.dirname(rel_path), spec))
    for candidate in [base + ext for ext in EXTENSIONS] + [f"{base}/index{e}" for e in EXTENSIONS]:
        if candidate in files:
            return candidate
    return None


def _package(spec: str) -> str | None:
    if spec.startswith("node:"):
        return None
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) > 1:
        return f"pkg:npm/{parts[0]}/{parts[1]}"
    return f"pkg:npm/{parts[0]}"


def _dotted(node: Node) -> tuple[str, ...] | None:
    if node.type == "identifier":
        return (_text(node),)
    if node.type == "member_expression":
        head = _dotted(node.child_by_field_name("object"))
        return head + (_text(node.child_by_field_name("property")),) if head else None
    return None


def _descendants(node: Node, node_type: str):
    for child in node.children:
        if child.type == node_type:
            yield child
        yield from _descendants(child, node_type)


def _string(node: Node) -> str:
    return _text(node)[1:-1]


def _text(node: Node) -> str:
    return node.text.decode()
