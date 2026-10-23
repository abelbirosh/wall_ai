"""Extract functions, imports and calls from Python source with tree-sitter."""

from __future__ import annotations

from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from wall_ai.understand.static.structure.facts import Call, FileFacts, Function, Import

_PARSER = Parser(Language(tree_sitter_python.language()))


def extract(source: bytes, rel_path: str, component_rel: str, files: set[str]) -> FileFacts:
    facts = FileFacts()
    root = _PARSER.parse(source).root_node
    for node in root.children:
        if node.type == "decorated_definition":
            node = node.child_by_field_name("definition")
        if node.type == "function_definition":
            _add_function(facts, node, _text(node.child_by_field_name("name")))
        elif node.type == "class_definition":
            cls = _text(node.child_by_field_name("name"))
            for member in node.child_by_field_name("body").children:
                if member.type == "decorated_definition":
                    member = member.child_by_field_name("definition")
                if member.type == "function_definition":
                    name = _text(member.child_by_field_name("name"))
                    _add_function(facts, member, f"{cls}.{name}")
        elif node.type in ("import_statement", "import_from_statement"):
            facts.imports.extend(_imports(node, rel_path, component_rel, files))
    return facts


def _add_function(facts: FileFacts, node: Node, name: str) -> None:
    facts.functions.append(Function(name, node.start_point.row + 1, node.end_point.row + 1))
    for call in _descendants(node.child_by_field_name("body"), "call"):
        target = _dotted(call.child_by_field_name("function"))
        if target:
            facts.calls.append(Call(name, target, call.start_point.row + 1))


def _imports(node: Node, rel_path: str, component_rel: str, files: set[str]) -> list[Import]:
    line = node.start_point.row + 1
    if node.type == "import_statement":
        result = []
        for name_node in node.children_by_field_name("name"):
            module, alias = _name_and_alias(name_node)
            file = _resolve(module, 0, rel_path, component_rel, files)
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
        if file := _resolve(submodule, level, rel_path, component_rel, files):
            result.append(Import(alias or symbol, file, None, None, line))
        elif file := _resolve(module, level, rel_path, component_rel, files):
            result.append(Import(alias or symbol, file, None, symbol, line))
        elif not level:
            result.append(Import(alias or symbol, None, _package(module), symbol, line))
    return result


def _resolve(module: str, level: int, rel_path: str, base: str, files: set[str]) -> str | None:
    if level:
        directory = PurePosixPath(rel_path).parent
        for _ in range(level - 1):
            directory = directory.parent
    else:
        directory = PurePosixPath(base)
    candidate = directory.joinpath(*module.split(".")) if module else directory
    for path in (f"{candidate}.py", f"{candidate}/__init__.py"):
        normalized = PurePosixPath(path).as_posix()
        if normalized in files:
            return normalized
    return None


def _package(module: str) -> str:
    return f"pkg:pypi/{module.split('.')[0].lower().replace('_', '-')}"


def _name_and_alias(node: Node) -> tuple[str, str | None]:
    if node.type == "aliased_import":
        return _text(node.child_by_field_name("name")), _text(node.child_by_field_name("alias"))
    return _text(node), None


def _dotted(node: Node) -> tuple[str, ...] | None:
    if node.type == "identifier":
        return (_text(node),)
    if node.type == "attribute":
        head = _dotted(node.child_by_field_name("object"))
        return head + (_text(node.child_by_field_name("attribute")),) if head else None
    return None


def _descendants(node: Node, node_type: str):
    for child in node.children:
        if child.type == node_type:
            yield child
        yield from _descendants(child, node_type)


def _text(node: Node) -> str:
    return node.text.decode()
