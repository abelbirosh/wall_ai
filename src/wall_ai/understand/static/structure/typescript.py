"""Extract functions, imports, calls and references from TypeScript/JavaScript with tree-sitter.

JSX elements count as calls: <UserList /> uses the UserList component.
"""

from __future__ import annotations

import posixpath

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

from wall_ai.understand.static.structure.facts import (
    MODULE,
    Call,
    Context,
    FileFacts,
    Function,
    Import,
)

_TS = Parser(Language(tree_sitter_typescript.language_typescript()))
_TSX = Parser(Language(tree_sitter_typescript.language_tsx()))

HTTP_VERBS = {"get", "post", "put", "patch", "delete"}
FUNCTION_VALUES = {"arrow_function", "function_expression", "function"}
EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
JSX_ELEMENTS = {"jsx_opening_element", "jsx_self_closing_element"}

# A name in one of these positions is used as a value: passed, returned, stored or rendered.
_VALUE_PARENTS = {"arguments", "array", "return_statement", "jsx_expression"}
_VALUE_FIELDS = {"pair": "value", "variable_declarator": "value", "assignment_expression": "right"}


def extract(source: bytes, ctx: Context) -> FileFacts:
    parser = _TSX if ctx.rel_path.endswith((".tsx", ".jsx")) else _TS
    facts = FileFacts()
    tree = parser.parse(source)  # keep the tree alive while its nodes are in use
    for node in tree.root_node.children:
        if node.type == "export_statement" and node.child_by_field_name("source"):
            facts.reexports.extend(_reexports(node, ctx))
            continue
        if node.type == "export_statement":
            node = _unwrap_export(facts, node, ctx)
        if node.type == "function_declaration":
            _add_function(facts, node, _text(node.child_by_field_name("name")))
        elif node.type == "class_declaration":
            _add_class(facts, node)
        elif node.type in ("lexical_declaration", "variable_declaration"):
            _add_declarations(facts, node)
        elif node.type == "import_statement":
            facts.imports.extend(_imports(node, ctx))
        elif node.type == "expression_statement" and _add_route_handler(facts, node):
            continue
        else:
            _scan(facts, node, MODULE)
    return facts


def _unwrap_export(facts: FileFacts, node: Node, ctx: Context) -> Node:
    """Return the exported declaration; record what `export default` points to."""
    is_default = any(c.type == "default" for c in node.children)
    declaration = node.child_by_field_name("declaration")
    if declaration is not None:
        name = declaration.child_by_field_name("name")
        if is_default and name is not None:
            facts.reexports.append(("default", _text(name), ctx.rel_path))
        return declaration
    value = node.child_by_field_name("value")
    if is_default and value is not None and value.type == "identifier":
        facts.reexports.append(("default", _text(value), ctx.rel_path))
    return node


def _add_declarations(facts: FileFacts, node: Node) -> None:
    for declarator in node.named_children:
        value = declarator.child_by_field_name("value")
        if value is not None and value.type in FUNCTION_VALUES:
            _add_function(facts, value, _text(declarator.child_by_field_name("name")))
        elif value is not None:
            _scan(facts, declarator, MODULE)


def _add_class(facts: FileFacts, node: Node) -> None:
    cls = _text(node.child_by_field_name("name"))
    for member in node.child_by_field_name("body").named_children:
        name_node = member.child_by_field_name("name")
        if member.type == "method_definition" and name_node is not None:
            _add_function(facts, member, f"{cls}.{_text(name_node)}")
        elif member.type == "public_field_definition":
            value = member.child_by_field_name("value")
            if value is not None and value.type in FUNCTION_VALUES and name_node is not None:
                _add_function(facts, value, f"{cls}.{_text(name_node)}")
            else:
                _scan(facts, member, MODULE)


def _add_route_handler(facts: FileFacts, statement: Node) -> bool:
    """Name inline handlers like app.post("/notify", async () => ...) as <POST /notify>."""
    call = statement.named_children[0] if statement.named_children else None
    if call is None or call.type != "call_expression":
        return False
    callee = call.child_by_field_name("function")
    if callee.type != "member_expression":
        return False
    verb = _text(callee.child_by_field_name("property"))
    args = call.child_by_field_name("arguments").named_children
    if verb not in HTTP_VERBS or not args or args[0].type != "string":
        return False
    handler = next((a for a in reversed(args) if a.type in FUNCTION_VALUES), None)
    if handler is None:
        return False
    _add_function(facts, handler, f"<{verb.upper()} {_string(args[0])}>")
    return True


def _add_function(facts: FileFacts, node: Node, name: str) -> None:
    facts.functions.append(Function(name, node.start_point.row + 1, node.end_point.row + 1))
    for part in ("parameters", "body"):
        _scan(facts, node.child_by_field_name(part), name)


def _scan(facts: FileFacts, node: Node | None, caller: str) -> None:
    """Record calls, rendered components and value references under node."""
    for child in _walk(node):
        line = child.start_point.row + 1
        if child.type == "call_expression":
            target = _dotted(child.child_by_field_name("function"))
            if target:
                facts.calls.append(Call(caller, target, line))
        elif child.type in JSX_ELEMENTS:
            target = _dotted(child.child_by_field_name("name"))
            if target and target[-1][:1].isupper():  # components, not <div>
                facts.calls.append(Call(caller, target, line))
        elif child.type == "shorthand_property_identifier":  # { Dashboard }
            facts.references.append(Call(caller, (_text(child),), line))
        elif child.type in ("identifier", "member_expression") and _is_value(child):
            target = _dotted(child)
            if target:
                facts.references.append(Call(caller, target, line))


def _is_value(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type in _VALUE_PARENTS:
        return True
    value_field = _VALUE_FIELDS.get(parent.type)
    return value_field is not None and parent.child_by_field_name(value_field) == node


def _imports(node: Node, ctx: Context) -> list[Import]:
    line = node.start_point.row + 1
    spec = _string(node.child_by_field_name("source"))
    file = _resolve(spec, ctx)
    package = None if file or spec.startswith(".") or _aliased(spec, ctx) else _package(spec)
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


def _reexports(node: Node, ctx: Context) -> list[tuple[str, str, str]]:
    file = _resolve(_string(node.child_by_field_name("source")), ctx)
    if file is None:
        return []
    clause = next((c for c in node.named_children if c.type == "export_clause"), None)
    if clause is None:
        return [("*", "*", file)]
    result = []
    for spec in clause.named_children:
        name = _text(spec.child_by_field_name("name"))
        alias = spec.child_by_field_name("alias")
        result.append((_text(alias) if alias else name, name, file))
    return result


def _resolve(spec: str, ctx: Context) -> str | None:
    if spec.startswith("."):
        base = posixpath.normpath(posixpath.join(posixpath.dirname(ctx.rel_path), spec))
    elif aliased := _aliased(spec, ctx):
        base = posixpath.normpath(aliased)
    else:
        return None
    for candidate in [base + ext for ext in EXTENSIONS] + [f"{base}/index{e}" for e in EXTENSIONS]:
        if candidate in ctx.files:
            return candidate
    return None


def _aliased(spec: str, ctx: Context) -> str | None:
    """Apply a tsconfig path alias: "@/client" with ("@/", "frontend/src/") gives
    "frontend/src/client"."""
    for prefix, replacement in ctx.aliases:
        if prefix.endswith("/") and spec.startswith(prefix):
            return replacement + spec[len(prefix) :]
        if spec == prefix:
            return replacement
    return None


def _package(spec: str) -> str | None:
    if spec.startswith("node:"):
        return None
    parts = spec.split("/")
    if spec.startswith("@") and len(parts) > 1:
        return f"pkg:npm/{parts[0]}/{parts[1]}"
    return f"pkg:npm/{parts[0]}"


def _dotted(node: Node | None) -> tuple[str, ...] | None:
    if node is None:
        return None
    if node.type in ("identifier", "property_identifier", "this"):
        return (_text(node),)
    if node.type in ("member_expression", "nested_identifier"):
        head = _dotted(node.child_by_field_name("object") or node.named_children[0])
        prop = node.child_by_field_name("property") or node.named_children[-1]
        return head + (_text(prop),) if head else None
    return None


def _walk(node: Node | None):
    if node is None:
        return
    for child in node.children:
        yield child
        yield from _walk(child)


def _string(node: Node) -> str:
    return _text(node)[1:-1]


def _text(node: Node) -> str:
    return node.text.decode()
