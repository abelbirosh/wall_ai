import pytest

from wall_ai.understand.model import Evidence, SystemModel


def _model_with_call(evidence: Evidence) -> SystemModel:
    model = SystemModel()
    model.add_node("function:a.py:f", "function")
    model.add_node("function:b.py:g", "function")
    model.add_edge("function:a.py:f", "function:b.py:g", "calls", evidence, source="a.py:3")
    return model


def test_add_node_is_idempotent_and_merges_attributes():
    model = SystemModel()
    model.add_node("pkg:pypi/httpx", "package", version="0.27.2")
    model.add_node("pkg:pypi/httpx", "package", license="BSD-3-Clause")

    [node] = model.nodes("package")
    assert node.attrs == {"version": "0.27.2", "license": "BSD-3-Clause"}


def test_add_node_rejects_kind_change():
    model = SystemModel()
    model.add_node("x", "file")
    with pytest.raises(ValueError):
        model.add_node("x", "function")


def test_add_edge_requires_both_nodes():
    model = SystemModel()
    model.add_node("a", "file")
    with pytest.raises(KeyError):
        model.add_edge("a", "missing", "imports", Evidence.STATIC, source="a:1")


def test_same_link_from_two_sources_merges_evidence():
    model = _model_with_call(Evidence.STATIC)
    model.add_edge(
        "function:a.py:f", "function:b.py:g", "calls", Evidence.OBSERVED, source="trace:42"
    )

    [edge] = model.edges("calls")
    assert edge.evidence == {Evidence.STATIC, Evidence.OBSERVED}
    assert edge.sources == ["a.py:3", "trace:42"]


def test_edges_filter_by_evidence():
    model = _model_with_call(Evidence.STATIC)
    assert model.edges(evidence=Evidence.STATIC)
    assert not model.edges(evidence=Evidence.OBSERVED)


def test_merge_combines_models():
    static = _model_with_call(Evidence.STATIC)
    observed = _model_with_call(Evidence.OBSERVED)
    observed.add_node("host:api.stripe.com", "host")

    static.merge(observed)

    assert static.node("host:api.stripe.com").kind == "host"
    [edge] = static.edges("calls")
    assert edge.evidence == {Evidence.STATIC, Evidence.OBSERVED}


def test_round_trip_through_dict():
    model = _model_with_call(Evidence.STATIC)
    model.add_node("pkg:npm/axios", "package", version="1.7.7")

    restored = SystemModel.from_dict(model.to_dict())

    assert restored.to_dict() == model.to_dict()


def test_unused_functions_ignore_endpoint_handlers():
    model = _model_with_call(Evidence.STATIC)
    model.add_node("function:a.py:handler", "function")
    model.add_node("endpoint:svc:GET /x", "endpoint")
    model.add_edge(
        "endpoint:svc:GET /x", "function:a.py:handler", "handled_by", Evidence.STATIC, source="a:9"
    )

    unused = {node.id for node in model.unused_functions()}

    # f has no callers but isn't a handler; g is called; handler serves an endpoint.
    assert unused == {"function:a.py:f"}
