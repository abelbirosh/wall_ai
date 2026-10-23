"""wall_ai runtime agent, loaded into every Python process of the target by wallai_agent.pth.

Does nothing unless WALLAI_OUT is set. When it is, it records:
- calls.json: caller -> callee pairs between the target's own functions, with counts,
  using sys.monitoring (Python 3.12+);
- spans.jsonl: OpenTelemetry spans from auto-instrumentation. Outbound (client) spans are
  tagged with the target function that made the call.
"""

import atexit
import json
import os
import sys
import threading
import time
from collections import Counter

ROOT = os.environ.get("WALLAI_ROOT", "")
OUT = os.environ.get("WALLAI_OUT", "")

_calls: Counter = Counter()
_runs: Counter = Counter()
_lock = threading.Lock()


_started = False


def start() -> None:
    # Venvs often link lib64 -> lib, so site processes this .pth twice; start only once.
    global _started
    if _started or not OUT or not ROOT or sys.version_info < (3, 12):
        return
    _started = True
    _start_call_tracer()
    _start_tracing()
    atexit.register(_write_calls)
    # Servers may exit by re-raising a signal, which skips atexit; keep a recent snapshot too.
    threading.Thread(target=_snapshot_loop, daemon=True, name="wallai-snapshot").start()


# --- call tracer -------------------------------------------------------------------------


def _is_target(code) -> bool:
    """The target's own named functions; not libraries, tests or <genexpr>/<lambda>."""
    path = code.co_filename
    if not path.startswith(ROOT + "/") or code.co_name.startswith("<"):
        return False
    rel = path[len(ROOT) + 1 :]
    name = os.path.basename(rel)
    return not (
        "/tests/" in f"/{rel}"
        or "/test/" in f"/{rel}"
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def _function_id(code) -> str:
    return f"{code.co_filename[len(ROOT) + 1 :]}:{code.co_qualname}"


def _nearest_target_frame(frame):
    while frame is not None and not _is_target(frame.f_code):
        frame = frame.f_back
    return frame


def _start_call_tracer() -> None:
    mon = sys.monitoring
    tool = next(t for t in (3, 4, 5) if mon.get_tool(t) is None)
    mon.use_tool_id(tool, "wallai")

    def on_start(code, offset):
        if not _is_target(code):
            return mon.DISABLE  # stop firing for this code object
        callee = _function_id(code)
        caller = _nearest_target_frame(sys._getframe(1).f_back)
        _runs[callee] += 1
        if caller is not None:
            _calls[(_function_id(caller.f_code), callee)] += 1

    mon.register_callback(tool, mon.events.PY_START, on_start)
    mon.set_events(tool, mon.events.PY_START)


def _snapshot_loop() -> None:
    while True:
        time.sleep(0.5)
        _write_calls()


def _write_calls() -> None:
    with _lock:
        data = {
            "functions": dict(_runs),
            "calls": [[caller, callee, n] for (caller, callee), n in list(_calls.items())],
        }
        path = os.path.join(OUT, f"calls-{os.getpid()}.json")
        with open(path + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(path + ".tmp", path)


# --- spans -------------------------------------------------------------------------------


def _start_tracing() -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.auto_instrumentation import initialize
        from opentelemetry.sdk.trace import SpanProcessor
        from opentelemetry.trace import SpanKind
    except ImportError:
        return

    class Recorder(SpanProcessor):
        def __init__(self) -> None:
            self._path = os.path.join(OUT, f"spans-{os.getpid()}.jsonl")

        def on_start(self, span, parent_context=None) -> None:
            if span.kind == SpanKind.CLIENT:
                frame = _nearest_target_frame(sys._getframe(1))
                if frame is not None:
                    span.set_attribute("wallai.caller", _function_id(frame.f_code))

        def on_end(self, span) -> None:
            record = {
                "name": span.name,
                "kind": span.kind.name,
                "attributes": dict(span.attributes or {}),
                "status": span.status.status_code.name,
            }
            with _lock, open(self._path, "a") as f:
                f.write(json.dumps(record, default=str) + "\n")

    initialize()
    provider = trace.get_tracer_provider()
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(Recorder())
