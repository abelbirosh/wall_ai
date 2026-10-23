# Understand: knowledge of existing software

The first wall_ai component. It builds a model of a target system's structure, dependencies, integrations and runtime behavior, which the later components (vulnerabilities, patches, testing, fallbacks) query.

## Scope

- **Languages (v1):** Python and JavaScript/TypeScript.
- **Access:** wall_ai reads the target's code *and* runs it in a sandbox.
- **Tool policy:** open-source tools with significant adoption. Copyleft tools are allowed only as separate, unmodified programs. wall_ai never bundles or links their code.

## Architecture

```
                 Target (repo + runnable build)
                   │                         │
        ┌──────────▼─────────┐     ┌─────────▼────────────┐
        │  STATIC PIPELINE   │     │   RUNTIME PIPELINE   │
        │  (reads the code)  │     │  (runs the software) │
        └──────────┬─────────┘     └─────────┬────────────┘
                   └──────────┬──────────────┘
                              ▼
                    Normalizer / Merger
                              ▼
                ┌─────────────────────────────┐
                │        SYSTEM MODEL         │
                │  one graph, every link has  │
                │  evidence: static, observed │
                │  or inferred                │
                └─────────────┬───────────────┘
                              ▼
          Query API / MCP  ·  CycloneDX export  ·  Reports
```

### Static pipeline

| Stage | Question | Tools |
|---|---|---|
| Inventory | What languages and components are there? | scc, cdxgen (Syft as cross-check) |
| Structure | How do files, modules and functions connect? | tree-sitter, scip-python, scip-typescript, Joern |
| Dependency usage | Which packages are actually called, and how? | cdxgen + atom, knip (JS/TS), dependency-cruiser (JS/TS) |
| Integrations | Which outside APIs and services does it talk to? | Semgrep / ast-grep (wall_ai's own rules), TruffleHog, Checkov / Trivy |
| Exposed API | Which endpoints does it serve? | atom, Joern route queries, published specs (e.g. FastAPI `/openapi.json`) |

#### Built so far (static)

Checked against two samples with ground truth, and against [fastapi/full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template).

- **Structure (tree-sitter, Python and TS):**
  - calls, including through `self`/`this` and imported classes;
  - functions used as values (callbacks, `Depends(...)`, props, `fn.bind`);
  - React components rendered as JSX;
  - code that runs at import time;
  - tsconfig path aliases, barrel re-exports and default exports.
- **Entry points:** functions a framework runs by convention aren't reported as unused: decorated functions, Alembic migrations and console scripts.
- **FastAPI:** finds the real app instance, and follows `include_router` chains to full route paths, including prefixes held in a settings constant.
- **Services:** wall_ai's own catalog (`rules/services.yml`) maps SDK imports, SBOM packages, connection strings, compose images and environment variables to services (databases, queues, email, monitoring, SaaS APIs).
- **Generated API clients:** calls by relative URL are matched to the backend endpoint they hit.
- **Not yet:** SCIP/Joern for precise resolution, data flow, atom reachability, and frameworks other than FastAPI and Express.

### Runtime pipeline

| Step | Tools |
|---|---|
| Sandbox | Firecracker microVM (kind inside it for Kubernetes targets). Outbound traffic goes through mitmproxy, which blocks, mocks or allows each call. |
| Instrument | OpenTelemetry eBPF Instrumentation (OBI), OpenTelemetry Python/Node agents, Tetragon, coverage.py / c8, Pyroscope |
| Drive | Replayed traffic (Keploy), the target's own tests (pytest, Jest/Vitest), synthetic load (Locust) |
| Capture | OpenTelemetry Collector, Jaeger for viewing |

eBPF tools need a Linux kernel, so local development on macOS needs a Linux VM (Lima or Colima). gVisor is not used because its syscall layer hides the app from eBPF.

#### Built so far (v1: Python)

Targets are treated as untrusted, including the user's own code.

- **Sandbox:** a Lima VM in plain mode (no host mounts or port forwarding) on macOS; on CI, the throwaway runner VM. Firecracker comes later.
- **Isolation:**
  - the target runs as an unprivileged user;
  - dependencies are installed from prebuilt wheels only, so no build scripts run;
  - after install, the user's network is cut to loopback only, and a probe confirms it.
- **Egress:** outbound HTTP goes through mitmproxy, which logs host, method and path (never queries, headers or bodies) and returns a mock response. `--allow-host` lets named hosts through for real.
- **Instrumentation:**
  - OpenTelemetry auto-instrumentation records server and client spans, and client spans are tagged with the calling function.
  - wall_ai's `sys.monitoring` tracer records caller→callee pairs with counts.
- **Traffic:** deterministic. One request per endpoint, from the static model plus the published OpenAPI spec (bodies from examples or schemas), then the target's own pytest suite.
- **Not yet:** TypeScript, OBI and Tetragon, Firecracker, Keploy replay, Locust load, LLM-guided traffic.

### System model

One graph.

- **Nodes:** files, modules, functions, packages, endpoints the target exposes, services (databases, SaaS APIs) and hosts.
- **Links:** `contains`, `imports`, `calls`, `references`, `depends_on`, `exposes`, `handled_by`, `talks_to`, `uses_service`. Links can carry attributes, such as how many times a link was observed.
- **Evidence:** every link records how it is known: `static` (found in code), `observed` (seen at runtime) or `inferred` (suggested by an LLM), plus a pointer to its source.

Comparing static and observed links separates:

- static links never observed: dead code, or paths the traffic didn't reach;
- observed links with no static match: dynamic dispatch, reflection or config-driven calls;
- links confirmed both ways: the strongest input for vulnerability reachability.

### Outputs

- A query API (and MCP server) for the other wall_ai components.
- A CycloneDX export of components and services.
- Human-readable reports.

## Licensing rules

1. Ship wall_ai's own detection rules. Don't pull from Semgrep's rule registry, whose license restricts use in competing products.
2. Don't ship wall_ai images with AGPL/GPL tools preinstalled. Install them at setup time, or run them as separate sidecar images.
3. Run copyleft tools unmodified. Any needed change is contributed upstream rather than kept as a fork.

## Excluded

| Tool | Reason |
|---|---|
| CodeQL | Not open source |
| GitNexus | Noncommercial license |
| mitmproxy2swagger | No license |
| gVisor | Hides the target from eBPF tracing |
| PyCG | Archived |

## Open questions

- Does "usage patterns" also cover how end users use the software (product analytics), or only runtime behavior?
- What form do targets usually come in: container images, Kubernetes manifests or plain repos?
- Are browser front-ends in scope for v1? They would need Playwright to drive them.
