"""Run the static pipeline on the fullstack sample and check it against the ground truth."""

import json
from pathlib import Path

import pytest

from wall_ai.understand.model import SystemModel
from wall_ai.understand.pipeline import understand

SAMPLE = Path(__file__).parents[2] / "samples" / "fullstack"
EXPECTED = json.loads((SAMPLE / "expected.json").read_text())

pytestmark = pytest.mark.functional


@pytest.fixture(scope="module")
def model() -> SystemModel:
    return understand(SAMPLE)


def _links(model: SystemModel, kind: str) -> set[tuple[str, str]]:
    return {(e.src, e.dst) for e in model.edges(kind)}


def _pairs(key: str) -> set[tuple[str, str]]:
    return {tuple(pair) for pair in EXPECTED[key]}


def test_serves_the_fastapi_app_not_a_router(model):
    apps = {n.id.split(":", 1)[1]: n.attrs.get("asgi_app") for n in model.nodes("component")}
    assert {k: v for k, v in apps.items() if v} == EXPECTED["asgi_app"]


def test_routes_get_their_full_mounted_paths(model):
    assert _links(model, "handled_by") == _pairs("endpoints")


def test_finds_calls_including_self_jsx_and_module_level(model):
    assert _links(model, "calls") == _pairs("calls")


def test_finds_functions_passed_as_values(model):
    assert _links(model, "references") == _pairs("references")


def test_resolves_tsconfig_path_aliases(model):
    assert _pairs("alias_imports") <= _links(model, "imports")


def test_finds_services_reached_through_sdks_and_config(model):
    found = {(s, d) for s, d in _links(model, "uses_service") if s.startswith("component:")}
    assert found == _pairs("services")


def test_links_the_generated_client_to_backend_endpoints(model):
    assert _links(model, "talks_to") == _pairs("talks_to")


def test_only_genuinely_unused_functions_are_flagged(model):
    assert {n.id for n in model.unused_functions()} == set(EXPECTED["unused_functions"])
