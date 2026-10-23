"""Language-neutral facts each extractor reports about one source file."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Function:
    name: str
    start: int  # 1-based, inclusive
    end: int


@dataclass
class Import:
    local: str | None  # name bound in this file; None for side-effect imports
    file: str | None = None  # resolved in-repo file, relative to the target root
    package: str | None = None  # package id, e.g. pkg:pypi/httpx
    symbol: str | None = None  # imported symbol; None means the whole module
    line: int = 0


@dataclass
class Call:
    caller: str  # enclosing function name
    target: tuple[str, ...]  # ("price_of",) or ("catalog", "price_of")
    line: int


@dataclass
class FileFacts:
    functions: list[Function] = field(default_factory=list)
    imports: list[Import] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
