"""Language-neutral facts each extractor reports about one source file."""

from __future__ import annotations

from dataclasses import dataclass, field

MODULE = "<module>"  # caller name for code that runs at import time, outside any function


@dataclass
class Context:
    """What an extractor needs to resolve imports in one file."""

    rel_path: str  # the file, relative to the target root
    component_rel: str  # its component's directory, relative to the target root
    files: set[str]  # every source file in the target
    aliases: list[tuple[str, str]] = field(default_factory=list)  # ("@/", "frontend/src/")


@dataclass
class Function:
    name: str
    start: int  # 1-based, inclusive
    end: int
    decorators: list[str] = field(default_factory=list)


@dataclass
class Import:
    local: str | None  # name bound in this file; None for side-effect imports
    file: str | None = None  # resolved in-repo file, relative to the target root
    package: str | None = None  # package id, e.g. pkg:pypi/httpx
    symbol: str | None = None  # imported symbol; None means the whole module
    line: int = 0


@dataclass
class Call:
    """A call, or a reference to a function used as a value (a callback, a dependency)."""

    caller: str  # enclosing function name, or MODULE
    target: tuple[str, ...]  # ("price_of",) or ("catalog", "price_of")
    line: int


@dataclass
class FileFacts:
    functions: list[Function] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    references: list[Call] = field(default_factory=list)
