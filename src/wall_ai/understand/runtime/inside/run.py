"""Runs inside the sandbox as root. Standard library only.

Usage: python3 run.py <staging dir>

The staging dir holds plan.json, target/ (a copy of the target) and inside/ (these scripts).
The target runs as an unprivileged user with no network except loopback. Its outbound
HTTP goes through mitmproxy, which logs every call and mocks the response.
Results land in <staging dir>/out.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import traceback
from pathlib import Path

USER = "wallai"
HOME = Path(f"/home/{USER}")
TARGET = HOME / "target"
OUT = HOME / "out"
TOOLS = Path("/opt/wallai")
PROXY_PORT = 8080
PYTHON_VERSION = "3.12"  # sys.monitoring, used by the call tracer, needs 3.12+
OTEL_PACKAGES = ["opentelemetry-distro"]
# Overlapping instrumentations double spans (fastapi+starlette, httpx+httpx2), and click wraps
# uvicorn's whole command in one span, which makes every request look nested and INTERNAL.
OTEL_DISABLED = "click,starlette,httpx2,asyncio,threading,logging,exceptions"

steps: list[dict] = []


def main(staging: Path) -> None:
    plan = json.loads((staging / "plan.json").read_text())
    inside = staging / "inside"
    proxy = None
    try:
        step("install tools", install_tools)
        step("reset sandbox user", reset_user, staging)
        python = step("install python", install_python)
        for comp in plan["components"]:
            step(f"{comp['name']}: environment", prepare_component, comp, python, inside)
        proxy = step("start egress proxy", start_proxy, inside, plan.get("allow_hosts", []))
        step("lock down network", lockdown)
        step("verify lockdown", verify_lockdown, python)
        for comp in plan["components"]:
            if comp.get("asgi_app"):
                step(f"{comp['name']}: serve and drive", serve_and_drive, comp, inside)
            if comp.get("tests"):
                step(f"{comp['name']}: run tests", run_tests, comp)
    finally:
        if proxy:
            stop(proxy)
        unlock()
        collect(staging, plan)


def step(name, fn, *args):
    started = time.time()
    try:
        result = fn(*args)
        steps.append({"name": name, "ok": True, "seconds": round(time.time() - started, 1)})
        return result
    except Exception as exc:  # recorded and surfaced in run.json, never swallowed silently
        detail = "".join(traceback.format_exception_only(exc)).strip()
        steps.append({"name": name, "ok": False, "detail": detail[-2000:]})
        raise


# --- setup -------------------------------------------------------------------------------


def install_tools() -> None:
    TOOLS.mkdir(parents=True, exist_ok=True)
    if not shutil.which("uv"):
        sh(
            "curl -LsSf https://astral.sh/uv/install.sh "
            "| env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh"
        )
    if not shutil.which("mitmdump"):
        run(
            ["uv", "tool", "install", "mitmproxy"],
            env={"UV_TOOL_DIR": "/opt/uv-tools", "UV_TOOL_BIN_DIR": "/usr/local/bin"},
        )


def install_python() -> str:
    env = {"UV_PYTHON_INSTALL_DIR": "/opt/uv-python"}
    run(["uv", "python", "install", PYTHON_VERSION], env=env)
    run(["chmod", "-R", "a+rX", "/opt/uv-python"])
    return run(["uv", "python", "find", PYTHON_VERSION], env=env).stdout.strip()


def reset_user(staging: Path) -> None:
    subprocess.run(["pkill", "-u", USER], check=False)
    subprocess.run(["userdel", "-r", USER], check=False, capture_output=True)
    run(["useradd", "--create-home", "--shell", "/bin/bash", USER])
    shutil.copytree(staging / "target", TARGET)
    OUT.mkdir()
    run(["chown", "-R", f"{USER}:{USER}", str(HOME)])


def prepare_component(comp: dict, python: str, inside: Path) -> None:
    venv = HOME / "venvs" / comp["name"]
    as_user(["uv", "venv", "--python", python, str(venv)])
    pip = [
        "uv",
        "pip",
        "install",
        "--python",
        str(venv / "bin" / "python"),
        "--only-binary",
        ":all:",
    ]
    component_dir = TARGET / comp["path"]
    if comp.get("requirements"):
        as_user(pip + ["-r", str(component_dir / comp["requirements"])])
    extras = OTEL_PACKAGES + (["pytest"] if comp.get("tests") else [])
    as_user(pip + extras)
    needed = as_user([str(venv / "bin" / "opentelemetry-bootstrap"), "-a", "requirements"])
    packages = [line for line in needed.stdout.split() if line]
    if packages:
        as_user(pip + packages)

    site = as_user(
        [
            str(venv / "bin" / "python"),
            "-c",
            "import sysconfig; print(sysconfig.get_path('purelib'))",
        ]
    ).stdout.strip()
    for name in ("wallai_agent.py", "wallai_agent.pth"):
        shutil.copy(inside / name, Path(site) / name)
    run(["chown", "-R", f"{USER}:{USER}", str(venv)])


def start_proxy(inside: Path, allow_hosts: list[str]) -> subprocess.Popen:
    env = {
        "WALLAI_EGRESS_LOG": str(OUT / "egress.jsonl"),
        "WALLAI_ALLOW_HOSTS": ",".join(allow_hosts),
    }
    proc = subprocess.Popen(
        ["mitmdump", "--listen-host", "127.0.0.1", "--listen-port", str(PROXY_PORT)]
        + ["--set", "confdir=/opt/wallai/mitmproxy", "-s", str(inside / "egress_addon.py")],
        env={**os.environ, **env},
        stdout=open(TOOLS / "proxy.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    wait_for_port(PROXY_PORT)
    ca = Path("/opt/wallai/mitmproxy/mitmproxy-ca-cert.pem")
    for _ in range(50):
        if ca.exists():
            break
        time.sleep(0.2)
    shutil.copy(ca, TOOLS / "ca.pem")
    os.chmod(TOOLS / "ca.pem", 0o644)
    return proc


# --- network lockdown --------------------------------------------------------------------

LOCKDOWN = [
    ["-o", "lo", "-m", "owner", "--uid-owner", USER, "-j", "ACCEPT"],
    ["-m", "owner", "--uid-owner", USER, "-j", "REJECT"],
]


def lockdown() -> None:
    for tool in ("iptables", "ip6tables"):
        for position, rule in enumerate(LOCKDOWN, start=1):
            run([tool, "-I", "OUTPUT", str(position)] + rule)


def unlock() -> None:
    for tool in ("iptables", "ip6tables"):
        for rule in LOCKDOWN:
            while (
                subprocess.run([tool, "-D", "OUTPUT"] + rule, capture_output=True).returncode == 0
            ):
                pass


def verify_lockdown(python: str) -> None:
    probe = "import socket; socket.create_connection(('1.1.1.1', 443), timeout=3)"
    result = as_user([python, "-c", probe], check=False)
    if result.returncode == 0:
        raise RuntimeError("sandbox user can still reach the internet")


# --- run the target ----------------------------------------------------------------------


def target_env(comp: dict, process: str) -> dict:
    out = OUT / comp["name"] / process
    out.mkdir(parents=True, exist_ok=True)
    run(["chown", "-R", f"{USER}:{USER}", str(OUT)])
    proxy = f"http://127.0.0.1:{PROXY_PORT}"
    venv_bin = HOME / "venvs" / comp["name"] / "bin"
    return {
        "PATH": f"{venv_bin}:/usr/local/bin:/usr/bin:/bin",
        "HTTP_PROXY": proxy,
        "HTTPS_PROXY": proxy,
        "http_proxy": proxy,
        "https_proxy": proxy,
        "NO_PROXY": "localhost,127.0.0.1,testserver",
        "no_proxy": "localhost,127.0.0.1,testserver",
        "SSL_CERT_FILE": str(TOOLS / "ca.pem"),
        "REQUESTS_CA_BUNDLE": str(TOOLS / "ca.pem"),
        "WALLAI_ROOT": str(TARGET),
        "WALLAI_OUT": str(out),
        "OTEL_SERVICE_NAME": comp["name"],
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
        "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": OTEL_DISABLED,
    }


def serve_and_drive(comp: dict, inside: Path) -> None:
    env = target_env(comp, "server")
    python = HOME / "venvs" / comp["name"] / "bin" / "python"
    server = subprocess.Popen(
        ["runuser", "-u", USER, "--", "env", "-i", *kv(env), str(python), "-m", "uvicorn"]
        + [comp["asgi_app"], "--host", "127.0.0.1", "--port", str(comp["port"])],
        cwd=TARGET / comp["path"],
        stdout=open(OUT / comp["name"] / "server.log", "w"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        wait_for_port(comp["port"], timeout=60)
        endpoints = OUT / comp["name"] / "endpoints.json"
        endpoints.write_text(json.dumps(comp["endpoints"]))
        run(
            [sys.executable, str(inside / "drive.py"), f"http://127.0.0.1:{comp['port']}"]
            + [str(endpoints), str(OUT / comp["name"] / "traffic.jsonl")]
        )
    finally:
        stop(server)


def run_tests(comp: dict) -> None:
    env = target_env(comp, "pytest")
    python = HOME / "venvs" / comp["name"] / "bin" / "python"
    result = subprocess.run(
        ["runuser", "-u", USER, "--", "env", "-i", *kv(env), str(python), "-m", "pytest"]
        + ["-q", "-p", "no:cacheprovider"],
        cwd=TARGET / comp["path"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    (OUT / comp["name"] / "pytest.log").write_text(result.stdout + result.stderr)


# --- helpers -----------------------------------------------------------------------------


def collect(staging: Path, plan: dict) -> None:
    dest = staging / "out"
    shutil.rmtree(dest, ignore_errors=True)
    if OUT.exists():
        shutil.copytree(OUT, dest)
    else:
        dest.mkdir()
    if (TOOLS / "proxy.log").exists():
        shutil.copy(TOOLS / "proxy.log", dest / "proxy.log")
    (dest / "run.json").write_text(json.dumps({"run_id": plan["run_id"], "steps": steps}, indent=2))
    subprocess.run(["chmod", "-R", "a+rX", str(dest)], check=False)


def stop(proc: subprocess.Popen) -> None:
    for sig, wait in ((signal.SIGTERM, 15), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
            proc.wait(timeout=wait)
            return
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            continue


def wait_for_port(port: int, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return
        except OSError:
            time.sleep(0.3)
    raise TimeoutError(f"nothing listening on port {port}")


def as_user(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    env = {"HOME": str(HOME), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    return run(["runuser", "-u", USER, "--", "env", "-i", *kv(env), *cmd], check=check)


def kv(env: dict) -> list[str]:
    return [f"{k}={v}" for k, v in env.items()]


def run(cmd: list[str], env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, env={**os.environ, **(env or {})}, capture_output=True, text=True, cwd="/"
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"{' '.join(cmd[:6])} failed: {(result.stderr or result.stdout)[-1500:]}"
        )
    return result


def sh(command: str) -> None:
    run(["bash", "-c", f"set -o pipefail; {command}"])


if __name__ == "__main__":
    try:
        main(Path(sys.argv[1]))
    except Exception:
        sys.exit(1)
