"""Run the Understand pipeline on the shopfront sample and check it against the ground truth."""

import json
from pathlib import Path

import pytest

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.pipeline import understand

SAMPLE = Path(__file__).parents[2] / "samples" / "shopfront"
EXPECTED = json.loads((SAMPLE / "expected.json").read_text())

pytestmark = pytest.mark.functional


@pytest.fixture(scope="module")
def model() -> SystemModel:
    return understand(SAMPLE)


def _links(model: SystemModel, kind: str) -> set[tuple[str, str]]:
    return {(e.src, e.dst) for e in model.edges(kind)}


def test_finds_components(model):
    assert {n.id for n in model.nodes("component")} == {
        f"component:{name}" for name in EXPECTED["components"]
    }


def test_finds_direct_packages(model):
    expected = {(f"component:{c}", pkg) for c, pkg in EXPECTED["packages"]}
    assert expected <= _links(model, "depends_on")


def test_finds_endpoints_and_handlers(model):
    assert {n.id for n in model.nodes("endpoint")} == {e for e, _ in EXPECTED["endpoints"]}
    assert _links(model, "handled_by") == {tuple(pair) for pair in EXPECTED["endpoints"]}


def test_finds_in_repo_imports(model):
    in_repo = {(s, d) for s, d in _links(model, "imports") if d.startswith("file:")}
    assert in_repo == {tuple(pair) for pair in EXPECTED["imports"]}


def test_finds_calls(model):
    assert _links(model, "calls") == {tuple(pair) for pair in EXPECTED["calls"]}


def test_finds_outbound_calls_including_the_other_service(model):
    assert _links(model, "talks_to") == {tuple(pair) for pair in EXPECTED["talks_to"]}


def test_flags_unused_functions(model):
    assert {n.id for n in model.unused_functions()} == set(EXPECTED["unused_functions"])


def test_every_link_is_static_with_a_source(model):
    for edge in model.edges():
        assert edge.evidence == {Evidence.STATIC}
        assert edge.sources
