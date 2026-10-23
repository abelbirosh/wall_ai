"""Deterministic traffic driver. Standard library only.

Usage: python3 drive.py <base url> <endpoints.json> <traffic log>

Sends one request to every endpoint the static model knows, plus any extra path the
target's published OpenAPI spec lists. Request bodies come from the spec: its examples
first, otherwise a value built from the schema. The same inputs always give the same
requests.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}


def main(base: str, endpoints_file: str, log_file: str) -> None:
    endpoints = json.loads(open(endpoints_file).read())
    spec = fetch_json(f"{base}/openapi.json") or {}
    known = {(e["method"], e["path"]) for e in endpoints}
    for path, operations in sorted(spec.get("paths", {}).items()):
        for method in sorted(operations):
            if (method.upper(), path) not in known and method.upper() in HTTP_METHODS:
                endpoints.append({"method": method.upper(), "path": path})

    with open(log_file, "w") as log:
        for ep in sorted(endpoints, key=lambda e: (e["path"], e["method"])):
            body = None
            if ep["method"] in METHODS_WITH_BODY:
                body = request_body(spec, ep["path"], ep["method"])
            status = send(ep["method"], base + fill_params(ep["path"]), body)
            log.write(json.dumps({**ep, "status": status}) + "\n")


HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def fill_params(path: str) -> str:
    """/items/{item_id} and /items/:id become /items/1."""
    return re.sub(r"\{[^}]+\}|:[A-Za-z_]\w*", "1", path)


def request_body(spec: dict, path: str, method: str):
    operation = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    media = operation.get("requestBody", {}).get("content", {}).get("application/json", {})
    if "example" in media:
        return media["example"]
    if media.get("examples"):
        first = sorted(media["examples"])[0]
        return media["examples"][first].get("value")
    return from_schema(spec, media.get("schema", {}), depth=0)


def from_schema(spec: dict, schema: dict, depth: int):
    if depth > 8:
        return None
    if "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec.get("components", {}).get("schemas", {}).get(name, {})
    if "example" in schema:
        return schema["example"]
    if schema.get("examples"):
        return schema["examples"][0]
    for combo in ("anyOf", "oneOf", "allOf"):
        if schema.get(combo):
            return from_schema(spec, schema[combo][0], depth + 1)
    kind = schema.get("type", "object")
    if kind == "object":
        props = schema.get("properties", {})
        return {k: from_schema(spec, v, depth + 1) for k, v in sorted(props.items())}
    if kind == "array":
        return [from_schema(spec, schema.get("items", {}), depth + 1)]
    return {"string": "string", "integer": 1, "number": 1.0, "boolean": True}.get(kind)


def fetch_json(url: str):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, ValueError, OSError):
        return None


def send(method: str, url: str, body) -> int:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except (urllib.error.URLError, OSError):
        return 0


if __name__ == "__main__":
    main(*sys.argv[1:4])
