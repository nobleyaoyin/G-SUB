"""Configuration for the standalone collaboration application."""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODE = os.environ.get("MANUSCRIPT_MODE", "development")
if MODE != "development":
    raise RuntimeError("Only collaboration development mode is supported")
# Compatibility for existing Main callers; no alternate environment is loaded.
IS_DEMO = False
DATA_ROOT = PROJECT_ROOT


def _env_bool(name: str) -> bool:
    value = os.environ.get(name, "false")
    if value not in {"true", "false"}:
        raise RuntimeError(f"Invalid {name}: expected true or false")
    return value == "true"


AI_PRESCREENING_ENABLED = _env_bool("AI_PRESCREENING_ENABLED")
AI_PRESCREENING_WORKER_ENABLED = _env_bool("AI_PRESCREENING_WORKER_ENABLED")


def guard_demo_path(path: Path) -> Path:
    """Compatibility with Main callers; retain development-mode behavior."""
    return Path(path)
