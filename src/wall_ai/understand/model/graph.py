"""The system model: one graph of a target, where every link records how it is known."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Evidence(StrEnum):
    STATIC = "static"  # found by reading the code
    OBSERVED = "observed"  # seen while the target ran
    INFERRED = "inferred"  # suggested by an LLM


@dataclass
class Node:
    id: str
    kind: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    src: str
    dst: str
    kind: str
    evidence: set[Evidence] = field(default_factory=set)
    sources: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.src, self.dst, self.kind)


class SystemModel:
    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str, str], Edge] = {}

    def add_node(self, node_id: str, kind: str, **attrs: Any) -> Node:
        node = self._nodes.get(node_id)
        if node is None:
            node = self._nodes[node_id] = Node(node_id, kind)
        elif node.kind != kind:
            raise ValueError(f"{node_id} is a {node.kind}, not a {kind}")
        node.attrs.update(attrs)
        return node

    def add_edge(self, src: str, dst: str, kind: str, evidence: Evidence, source: str) -> Edge:
        for node_id in (src, dst):
            if node_id not in self._nodes:
                raise KeyError(node_id)
        edge = self._edges.setdefault((src, dst, kind), Edge(src, dst, kind))
        edge.evidence.add(evidence)
        if source not in edge.sources:
            edge.sources.append(source)
        return edge

    def node(self, node_id: str) -> Node:
        return self._nodes[node_id]

    def nodes(self, kind: str | None = None) -> list[Node]:
        return [n for n in self._nodes.values() if kind is None or n.kind == kind]

    def edges(self, kind: str | None = None, evidence: Evidence | None = None) -> list[Edge]:
        return [
            e
            for e in self._edges.values()
            if (kind is None or e.kind == kind) and (evidence is None or evidence in e.evidence)
        ]

    def merge(self, other: SystemModel) -> None:
        for node in other.nodes():
            self.add_node(node.id, node.kind, **node.attrs)
        for edge in other.edges():
            for evidence in sorted(edge.evidence):
                for source in edge.sources:
                    self.add_edge(edge.src, edge.dst, edge.kind, evidence, source)

    def unused_functions(self) -> list[Node]:
        """Functions nothing calls and no endpoint is handled by."""
        reached = {e.dst for e in self.edges() if e.kind in ("calls", "handled_by")}
        return [n for n in self.nodes("function") if n.id not in reached]

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.id, "kind": n.kind, "attrs": n.attrs}
                for n in sorted(self._nodes.values(), key=lambda n: n.id)
            ],
            "edges": [
                {
                    "src": e.src,
                    "dst": e.dst,
                    "kind": e.kind,
                    "evidence": sorted(e.evidence),
                    "sources": e.sources,
                }
                for e in sorted(self._edges.values(), key=lambda e: e.key)
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemModel:
        model = cls()
        for n in data["nodes"]:
            model.add_node(n["id"], n["kind"], **n["attrs"])
        for e in data["edges"]:
            edge = model._edges.setdefault(
                (e["src"], e["dst"], e["kind"]), Edge(e["src"], e["dst"], e["kind"])
            )
            edge.evidence.update(Evidence(v) for v in e["evidence"])
            edge.sources.extend(e["sources"])
        return model
