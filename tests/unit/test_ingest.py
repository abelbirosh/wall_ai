import json

import pytest

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.runtime.ingest import ingest, not_executed

RUN = "run:test"


@pytest.fixture
def model() -> SystemModel:
    m = SystemModel()
    m.add_node("component:api", "component")
    for path in ("api/app/main.py", "api/app/catalog.py", "api/app/payments.py"):
        m.add_node(f"file:{path}", "file", component="api")
    for fn in (
        "api/app/main.py:list_products",
        "api/app/catalog.py:all_products",
        "api/app/catalog.py:legacy_discount",
        "api/app/payments.py:charge",
    ):
        m.add_node(f"function:{fn}", "function", file=fn.split(":")[0])
    m.add_node("endpoint:api:GET /products", "endpoint")
    m.add_edge("component:api", "endpoint:api:GET /products", "exposes", Evidence.STATIC, "s")
    m.add_edge(
        "endpoint:api:GET /products",
        "function:api/app/main.py:list_products",
        "handled_by",
        Evidence.STATIC,
        "s",
    )
    m.add_edge(
        "function:api/app/main.py:list_products",
        "function:api/app/catalog.py:all_products",
        "calls",
        Evidence.STATIC,
        "s",
    )
    return m


@pytest.fixture
def out(tmp_path):
    server = tmp_path / "api" / "server"
    server.mkdir(parents=True)
    spans = [
        {"kind": "SERVER", "attributes": {"http.route": "/products", "http.method": "GET"}},
        {"kind": "SERVER", "attributes": {"http.route": "/products", "http.method": "GET"}},
        {"kind": "SERVER", "attributes": {"http.route": "/health", "http.request.method": "GET"}},
        {"kind": "SERVER", "attributes": {"http.request.method": "GET"}},  # 404: no route
        {
            "kind": "CLIENT",
            "attributes": {
                "url.full": "https://api.stripe.com/v1/charges?key=secret",
                "wallai.caller": "api/app/payments.py:charge",
            },
        },
        {"kind": "CLIENT", "attributes": {"http.url": "http://testserver/products"}},
    ]
    (server / "spans-1.jsonl").write_text("".join(json.dumps(s) + "\n" for s in spans))
    calls = {
        "functions": {
            "api/app/main.py:list_products": 2,
            "api/app/catalog.py:all_products": 2,
            "api/app/payments.py:charge": 1,
            "api/app/main.py:helper.<locals>.inner": 1,
        },
        "calls": [
            ["api/app/main.py:list_products", "api/app/catalog.py:all_products", 2],
            ["api/app/main.py:list_products", "api/app/main.py:helper.<locals>.inner", 1],
        ],
    }
    (server / "calls-1.json").write_text(json.dumps(calls))
    egress = [{"host": "api.stripe.com", "action": "mocked"}] * 2
    (tmp_path / "egress.jsonl").write_text("".join(json.dumps(e) + "\n" for e in egress))
    return tmp_path


def _edge(model, src, dst, kind):
    return next(e for e in model.edges(kind) if e.src == src and e.dst == dst)


def test_observed_call_confirms_static_call_with_count(model, out):
    ingest(model, out, RUN)

    edge = _edge(
        model,
        "function:api/app/main.py:list_products",
        "function:api/app/catalog.py:all_products",
        "calls",
    )
    assert edge.evidence == {Evidence.STATIC, Evidence.OBSERVED}
    assert edge.attrs["count"] == 2
    assert RUN in edge.sources


def test_call_static_analysis_missed_is_observed_only(model, out):
    ingest(model, out, RUN)

    inner = "function:api/app/main.py:helper.<locals>.inner"
    assert model.node(inner).kind == "function"
    edge = _edge(model, "function:api/app/main.py:list_products", inner, "calls")
    assert edge.evidence == {Evidence.OBSERVED}


def test_server_spans_observe_endpoints_and_handlers(model, out):
    ingest(model, out, RUN)

    exposes = _edge(model, "component:api", "endpoint:api:GET /products", "exposes")
    assert exposes.evidence == {Evidence.STATIC, Evidence.OBSERVED}
    assert exposes.attrs["count"] == 2
    handled = _edge(
        model, "endpoint:api:GET /products", "function:api/app/main.py:list_products", "handled_by"
    )
    assert Evidence.OBSERVED in handled.evidence
    health = _edge(model, "component:api", "endpoint:api:GET /health", "exposes")
    assert health.evidence == {Evidence.OBSERVED}


def test_client_spans_observe_outbound_calls_and_skip_loopback(model, out):
    ingest(model, out, RUN)

    edge = _edge(model, "function:api/app/payments.py:charge", "host:api.stripe.com", "talks_to")
    assert edge.evidence == {Evidence.OBSERVED}
    assert all("testserver" not in n.id for n in model.nodes("host"))


def test_egress_log_marks_hosts_as_mocked(model, out):
    ingest(model, out, RUN)

    assert model.node("host:api.stripe.com").attrs["egress"] == {"mocked": 2}


def test_functions_never_executed_only_count_components_that_ran(model, out):
    model.add_node("component:notifier", "component")
    model.add_node("file:notifier/src/email.ts", "file", component="notifier")
    model.add_node(
        "function:notifier/src/email.ts:sendEmail", "function", file="notifier/src/email.ts"
    )

    ingest(model, out, RUN)

    assert model.node("function:api/app/main.py:list_products").attrs["executed"] == 2
    assert {n.id for n in not_executed(model)} == {"function:api/app/catalog.py:legacy_discount"}
