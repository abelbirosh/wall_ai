"""Extract functions, imports, calls and references from Python source with tree-sitter."""

from __future__ import annotations

from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from wall_ai.understand.static.structure.facts import (
    MODULE,
    Call,
    Context,
    FileFacts,
    Function,
    Import,
)

_PARSER = Parser(Language(tree_sitter_python.language()))

# A name in one of these positions is used as a value: passed, returned, stored or defaulted.
_VALUE_PARENTS = {"argument_list", "list", "tuple", "set", "return_statement", "expression_list"}
_VALUE_FIELDS = {
    "keyword_argument": "value",
    "default_parameter": "value",
    "typed_default_parameter": "value",
    "pair": "value",
    "assignment": "right",
}


def extract(source: bytes, ctx: Context) -> FileFacts:
    facts = FileFacts()
    tree = _PARSER.parse(source)  # keep the tree alive while its nodes are in use
    for node in tree.root_node.children:
        decorators = []
        if node.type == "decorated_definition":
            decorators = [d for d in node.children if d.type == "decorator"]
            for decorator in decorators:
                _scan(facts, decorator, MODULE)
            node = node.child_by_field_name("definition")
        if node.type == "function_definition":
            _add_function(facts, node, _text(node.child_by_field_name("name")), decorators)
        elif node.type == "class_definition":
            _add_class(facts, node)
        elif node.type in ("import_statement", "import_from_statement"):
            facts.imports.extend(_imports(node, ctx))
        else:
            _scan(facts, node, MODULE)
    return facts


def _add_class(facts: FileFacts, node: Node) -> None:
    cls = _text(node.child_by_field_name("name"))
    for member in node.child_by_field_name("body").children:
        decorators = []
        if member.type == "decorated_definition":
            decorators = [d for d in member.children if d.type == "decorator"]
            for decorator in decorators:
                _scan(facts, decorator, MODULE)
            member = member.child_by_field_name("definition")
        if member.type == "function_definition":
            name = _text(member.child_by_field_name("name"))
            _add_function(facts, member, f"{cls}.{name}", decorators)
        else:
            _scan(facts, member, MODULE)  # class attributes, e.g. Field(default_factory=fn)


def _add_function(facts: FileFacts, node: Node, name: str, decorators: list[Node]) -> None:
    names = [_decorator_name(d) for d in decorators]
    facts.functions.append(Function(name, node.start_point.row + 1, node.end_point.row + 1, names))
    for part in ("parameters", "body"):
        _scan(facts, node.child_by_field_name(part), name)


def _scan(facts: FileFacts, node: Node, caller: str) -> None:
    """Record calls and value references anywhere under node, attributed to caller."""
    for child in _walk(node):
        if child.type == "call":
            target = _dotted(child.child_by_field_name("function"))
            if target:
                facts.calls.append(Call(caller, target, child.start_point.row + 1))
        elif child.type in ("identifier", "attribute") and _is_value(child):
            target = _dotted(child)
            if target:
                facts.references.append(Call(caller, target, child.start_point.row + 1))


def _is_value(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type in _VALUE_PARENTS:
        return True
    value_field = _VALUE_FIELDS.get(parent.type)
    return value_field is not None and parent.child_by_field_name(value_field) == node


def _decorator_name(node: Node) -> str:
    expr = next(c for c in node.children if c.type != "@")
    if expr.type == "call":
        expr = expr.child_by_field_name("function")
    return ".".join(_dotted(expr) or (_text(expr),))


def _imports(node: Node, ctx: Context) -> list[Import]:
    line = node.start_point.row + 1
    if node.type == "import_statement":
        result = []
        for name_node in node.children_by_field_name("name"):
            module, alias = _name_and_alias(name_node)
            file = _resolve(module, 0, ctx)
            result.append(
                Import(alias or module, file, None if file else _package(module), None, line)
            )
        return result

    module_node = node.child_by_field_name("module_name")
    level, module = 0, _text(module_node)
    if module_node.type == "relative_import":
        level = module.count(".") - module.lstrip(".").count(".")
        module = module.lstrip(".")
    result = []
    for name_node in node.children_by_field_name("name"):
        symbol, alias = _name_and_alias(name_node)
        submodule = f"{module}.{symbol}" if module else symbol
        if file := _resolve(submodule, level, ctx):
            result.append(Import(alias or symbol, file, None, None, line))
        elif file := _resolve(module, level, ctx):
            result.append(Import(alias or symbol, file, None, symbol, line))
        elif not level:
            result.append(Import(alias or symbol, None, _package(module), symbol, line))
    return result


def _resolve(module: str, level: int, ctx: Context) -> str | None:
    if level:
        directory = PurePosixPath(ctx.rel_path).parent
        for _ in range(level - 1):
            directory = directory.parent
    else:
        directory = PurePosixPath(ctx.component_rel)
    candidate = directory.joinpath(*module.split(".")) if module else directory
    for path in (f"{candidate}.py", f"{candidate}/__init__.py"):
        normalized = PurePosixPath(path).as_posix()
        if normalized in ctx.files:
            return normalized
    return None


def _package(module: str) -> str:
    return f"pkg:pypi/{module.split('.')[0].lower().replace('_', '-')}"


def _name_and_alias(node: Node) -> tuple[str, str | None]:
    if node.type == "aliased_import":
        return _text(node.child_by_field_name("name")), _text(node.child_by_field_name("alias"))
    return _text(node), None


def _dotted(node: Node | None) -> tuple[str, ...] | None:
    if node is None:
        return None
    if node.type == "identifier":
        return (_text(node),)
    if node.type == "attribute":
        head = _dotted(node.child_by_field_name("object"))
        return head + (_text(node.child_by_field_name("attribute")),) if head else None
    return None


def _walk(node: Node | None):
    if node is None:
        return
    for child in node.children:
        yield child
        yield from _walk(child)


def _text(node: Node) -> str:
    return node.text.decode()
