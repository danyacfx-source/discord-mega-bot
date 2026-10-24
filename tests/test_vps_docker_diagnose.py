"""Basic safety and shell syntax checks for host-side Docker diagnostics."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vps_docker_diagnose.sh"


def test_diagnostic_shell_is_parseable() -> None:
    bash = shutil.which("bash")
    if bash:
        subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_diagnostics_remain_read_only_and_secrets_safe() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    assert "docker compose --profile postgres config --quiet" in script
    assert "docker inspect --format" in script
    assert "OOMKilled=" in script
    assert "RestartCount=" in script
    assert "Config.Env" not in "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )
    for forbidden in ("docker compose down", "docker system prune", "docker compose up", "docker compose restart"):
        assert forbidden not in script
