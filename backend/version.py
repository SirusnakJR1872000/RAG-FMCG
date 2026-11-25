"""Application version and the git commit it runs (shown in SYSTEM_START and /health/details)."""

import subprocess
from pathlib import Path

APP_VERSION = "0.1.0"


def git_commit() -> str:
    try:
        out = subprocess.run(  # noqa: S603 — fixed arguments
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=Path(__file__).parent, capture_output=True, text=True, check=False, timeout=5)
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"
