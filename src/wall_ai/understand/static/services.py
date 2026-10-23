"""Services: databases, queues and SaaS APIs the target reaches through SDKs and config.

Most integrations have no URL in the code: a database comes from a connection string built
from settings, an email or monitoring service from its SDK. This finds them from four kinds
of evidence, using wall_ai's own catalog (rules/services.yml):
imports in the code, packages in the SBOM, connection strings, and compose files.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from wall_ai.understand.model import Evidence, SystemModel
from wall_ai.understand.static.components import SKIP_DIRS, Component, owning_component
from wall_ai.understand.static.structure.facts import FileFacts

CATALOG = Path(__file__).parent / "rules" / "services.yml"
CONFIG_FILES = {".env", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf"}
COMPOSE_NAMES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")


def add_services(
    model: SystemModel, root: Path, components: list[Component], facts: dict[str, FileFacts]
) -> None:
    root = root.resolve()
    catalog = Catalog(yaml.safe_load(CATALOG.read_text())["services"])
    found = Found(model, catalog)

    for rel, file_facts in facts.items():
        component = owning_component(components, root / rel)
        for imp in file_facts.imports:
            if imp.package and (service := catalog.for_import(imp.package)):
                found.add(component, service, f"{rel}:{imp.line}", file=rel)

    for component in components:
        for edge in model.edges("depends_on"):
            if edge.src == f"component:{component.name}":
                if service := catalog.for_package(edge.dst):
                    found.add(component, service, f"sbom:{edge.dst}")

    scheme = re.compile(rb"\b(" + b"|".join(catalog.schemes_pattern) + rb")(?:\+[\w-]+)?://")
    for path in _text_files(root):
        rel = path.relative_to(root).as_posix()
        component = owning_component(components, path)
        if component is None:
            continue
        for match in scheme.finditer(path.read_bytes()):
            if service := catalog.for_scheme(match.group(1).decode().lower()):
                found.add(component, service, f"{rel}:connection string", file=rel)

    for compose in sorted(p for name in COMPOSE_NAMES for p in root.rglob(name)):
        if not SKIP_DIRS.intersection(compose.relative_to(root).parts):
            _compose(found, catalog, root, components, compose)


class Catalog:
    def __init__(self, services: dict) -> None:
        self.services = services
        self.schemes_pattern = sorted(
            {re.escape(s).encode() for spec in services.values() for s in spec.get("schemes", [])},
            key=len,
            reverse=True,
        )

    def _match(self, field: str, name: str) -> str | None:
        name = name.lower()
        for service, spec in self.services.items():
            for entry in spec.get(field, []):
                if entry.endswith("*") and name.startswith(entry[:-1]) or name == entry:
                    return service
        return None

    def for_import(self, package_id: str) -> str | None:
        ecosystem, _, name = package_id.removeprefix("pkg:").partition("/")
        return self._match("python" if ecosystem == "pypi" else "npm", name.replace("_", "-"))

    def for_package(self, package_id: str) -> str | None:
        ecosystem, _, name = package_id.removeprefix("pkg:").partition("/")
        return self._match(ecosystem, name) if ecosystem in ("pypi", "npm") else None

    def for_scheme(self, scheme: str) -> str | None:
        return self._match("schemes", scheme)

    def for_image(self, image: str) -> str | None:
        name = image.split("@")[0].rsplit(":", 1)[0] if ":" in image.split("/")[-1] else image
        name = name.removeprefix("docker.io/").removeprefix("library/")
        return self._match("images", name)

    def for_env(self, key: str) -> str | None:
        for service, spec in self.services.items():
            if any(key.upper().startswith(prefix) for prefix in spec.get("env", [])):
                return service
        return None


class Found:
    def __init__(self, model: SystemModel, catalog: Catalog) -> None:
        self.model = model
        self.catalog = catalog

    def add(self, component: Component, service: str, source: str, file: str | None = None):
        service_id = f"service:{service}"
        category = self.catalog.services[service].get("category")
        self.model.add_node(service_id, "service", category=category)
        component_id = f"component:{component.name}"
        self.model.add_edge(component_id, service_id, "uses_service", Evidence.STATIC, source)
        if file and any(n.id == f"file:{file}" for n in self.model.nodes("file")):
            # Source files get their own link; config files (.env, YAML) only name the source.
            self.model.add_edge(f"file:{file}", service_id, "uses_service", Evidence.STATIC, source)


def _compose(found: Found, catalog: Catalog, root: Path, components, compose: Path) -> None:
    try:
        services = (yaml.safe_load(compose.read_text()) or {}).get("services", {}) or {}
    except yaml.YAMLError:
        return
    rel = compose.relative_to(root).as_posix()
    known = {}  # compose service name -> catalog service
    for name, spec in services.items():
        if isinstance(spec, dict) and (service := catalog.for_image(str(spec.get("image", "")))):
            known[name] = service
            found.model.add_node(f"service:{service}", "service", image=spec["image"])
    for name, spec in services.items():
        if not isinstance(spec, dict) or "build" not in spec:
            continue
        build = spec["build"]
        context = build.get("context", ".") if isinstance(build, dict) else build
        location = (compose.parent / context).resolve() / "x"
        if isinstance(build, dict) and build.get("dockerfile"):  # context ".", backend/Dockerfile
            location = (compose.parent / context / build["dockerfile"]).resolve()
        component = owning_component(components, location)
        if component is None:
            continue
        depends = spec.get("depends_on", [])
        for dependency in depends if isinstance(depends, list) else list(depends):
            if dependency in known:
                found.add(component, known[dependency], f"{rel}:{name}.depends_on")
        env = spec.get("environment", {})
        keys = env if isinstance(env, list) else list(env)
        for key in (str(k).split("=")[0] for k in keys):
            if service := catalog.for_env(key):
                found.add(component, service, f"{rel}:{name}.environment.{key}")


def _text_files(root: Path):
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts
        if SKIP_DIRS.intersection(parts) or not path.is_file():
            continue
        if path.suffix in (".py", ".ts", ".tsx", ".js", ".jsx") or path.suffix in CONFIG_FILES:
            yield path
        elif path.name.startswith(".env"):
            yield path
