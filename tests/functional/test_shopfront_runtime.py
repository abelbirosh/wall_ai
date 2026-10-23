"""Run the shopfront sample in a sandbox and check what was observed against the ground truth."""

import json
import os
import shutil
from pathlib import Path

import pytest

from wall_ai.understand.pipeline import understand
from wall_ai.understand.runtime.ingest import not_executed
from wall_ai.understand.runtime.observe import observe
from wall_ai.understand.runtime.sandbox import default_sandbox
from wall_ai.understand.static.components import find_components

SAMPLE = Path(__file__).parents[2] / "samples" / "shopfront"
EXPECTED = json.loads((SAMPLE / "expected_runtime.json").read_text())

pytestmark = [
    pytest.mark.functional,
    pytest.mark.skipif(
        os.environ.get("WALL_AI_EPHEMERAL") != "1" and shutil.which("limactl") is None,
        reason="needs a sandbox: Lima, or WALL_AI_EPHEMERAL=1 on a throwaway Linux VM",
    ),
]


@pytest.fixture(scope="module")
def observed():
    model = understand(SAMPLE)
    run = observe(model, SAMPLE, find_components(SAMPLE), default_sandbox())
    return model, run


def test_every_sandbox_step_succeeds(observed):
    _, run = observed
    failed = [s for s in run["steps"] if not s["ok"]]
    assert not failed, failed


def test_only_python_components_ran(observed):
    model, _ = observed
    ran = sorted(n.id.split(":", 1)[1] for n in model.nodes("component") if n.attrs.get("ran_in"))
    assert ran == EXPECTED["ran"]


@pytest.mark.parametrize("kind", ["exposes", "handled_by", "calls", "talks_to"])
def test_runtime_confirms_static_links(observed, kind):
    model, _ = observed
    split = model.compare(kind)
    ran = tuple(f"{t}:{c}" for c in EXPECTED["ran"] for t in ("component", "endpoint", "function"))
    in_run = lambda edges: {(e.src, e.dst) for e in edges if e.src.startswith(ran)}  # noqa: E731
    assert in_run(split["confirmed"]) == {tuple(p) for p in EXPECTED[kind]["confirmed"]}
    assert in_run(split["observed_only"]) == {tuple(p) for p in EXPECTED[kind]["observed_only"]}


def test_outbound_calls_were_mocked(observed):
    model, _ = observed
    egress = {n.id[5:]: n.attrs["egress"] for n in model.nodes("host") if "egress" in n.attrs}
    assert egress == EXPECTED["egress"]


def test_flags_code_that_never_ran(observed):
    model, _ = observed
    assert {n.id for n in not_executed(model)} == set(EXPECTED["never_executed"])
