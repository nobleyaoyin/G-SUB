"""Configuration for the standalone collaboration application."""
from dataclasses import dataclass
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


@dataclass(frozen=True)
class SMTPSettings:
    host: str
    port: int
    username: str | None
    password: str | None
    sender_email: str
    sender_name: str
    use_tls: bool
    use_ssl: bool
    timeout: float = 10.0


def load_smtp_settings() -> SMTPSettings | None:
    """Load optional workflow SMTP settings from the process environment."""
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        return None

    try:
        port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        raise ValueError("Invalid SMTP_PORT") from None
    if not 1 <= port <= 65535:
        raise ValueError("Invalid SMTP_PORT")

    username = os.environ.get("SMTP_USERNAME", "").strip() or None
    password = os.environ.get("SMTP_PASSWORD", "") or None
    if (username is None) != (password is None):
        raise ValueError("SMTP_USERNAME and SMTP_PASSWORD must be configured together")

    sender_email = os.environ.get("SMTP_FROM_EMAIL", "").strip()
    if not sender_email:
        raise ValueError("SMTP_FROM_EMAIL is required when SMTP_HOST is configured")

    def setting_bool(name: str, default: str) -> bool:
        value = os.environ.get(name, default)
        if value not in {"true", "false"}:
            raise ValueError(f"Invalid {name}: expected true or false")
        return value == "true"

    use_tls = setting_bool("SMTP_USE_TLS", "true")
    use_ssl = setting_bool("SMTP_USE_SSL", "false")
    if use_tls and use_ssl:
        raise ValueError("SMTP_USE_TLS and SMTP_USE_SSL cannot both be true")

    return SMTPSettings(
        host=host,
        port=port,
        username=username,
        password=password,
        sender_email=sender_email,
        sender_name=os.environ.get("SMTP_FROM_NAME", "G-Sub").strip() or "G-Sub",
        use_tls=use_tls,
        use_ssl=use_ssl,
    )


def guard_demo_path(path: Path) -> Path:
    """Compatibility with Main callers; retain development-mode behavior."""
    return Path(path)
