"""Where the target runs. Every backend is a Linux machine with root, isolated from the host.

- LimaSandbox: a Lima VM in plain mode (no host mounts, no port forwarding). For macOS.
- EphemeralSandbox: the current Linux machine, for throwaway VMs such as CI runners only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REMOTE = "/tmp/wallai-run"


class LimaSandbox:
    def __init__(self, name: str = "wallai-sandbox") -> None:
        if shutil.which("limactl") is None:
            raise RuntimeError("limactl not found; install Lima with: brew install lima")
        self.name = name

    def run(self, staging: Path, dest: Path) -> None:
        self._ensure_running()
        self._shell(["sudo", "rm", "-rf", REMOTE])
        _check(["limactl", "copy", "-r", str(staging), f"{self.name}:{REMOTE}"])
        self._shell(["sudo", "python3", f"{REMOTE}/inside/run.py", REMOTE], check=False)
        _check(["limactl", "copy", "-r", f"{self.name}:{REMOTE}/out", str(dest)])

    def _ensure_running(self) -> None:
        listing = _check(["limactl", "list", "--json"]).stdout
        instances = {i["name"]: i for i in map(json.loads, listing.splitlines() if listing else [])}
        if self.name not in instances:
            _check(
                ["limactl", "create", f"--name={self.name}", "--plain", "--cpus=2", "--memory=4"]
                + ["--tty=false", "template:ubuntu-24.04"]
            )
        if instances.get(self.name, {}).get("status") != "Running":
            _check(["limactl", "start", self.name, "--tty=false"])

    def _shell(self, cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
        return _check(["limactl", "shell", "--workdir", "/", self.name, "--", *cmd], check)


class EphemeralSandbox:
    """Runs the target on this machine. Only for disposable Linux VMs, such as CI runners."""

    def __init__(self) -> None:
        if sys.platform != "linux" or os.environ.get("WALL_AI_EPHEMERAL") != "1":
            raise RuntimeError(
                "the ephemeral sandbox runs untrusted code on this machine; use it only on a "
                "throwaway Linux VM (such as a CI runner) and set WALL_AI_EPHEMERAL=1"
            )

    def run(self, staging: Path, dest: Path) -> None:
        _check(["sudo", "rm", "-rf", REMOTE])
        shutil.copytree(staging, REMOTE)
        _check(["sudo", "python3", f"{REMOTE}/inside/run.py", REMOTE], check=False)
        shutil.copytree(f"{REMOTE}/out", dest)


def default_sandbox() -> LimaSandbox | EphemeralSandbox:
    if os.environ.get("WALL_AI_EPHEMERAL") == "1":
        return EphemeralSandbox()
    return LimaSandbox()


def _check(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])} failed: {result.stderr[-1500:]}")
    return result
