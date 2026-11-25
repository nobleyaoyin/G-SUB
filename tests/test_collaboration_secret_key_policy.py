"""Isolated startup checks for the Collaboration JWT signing key."""
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest


PROJECT = Path(__file__).resolve().parents[1]


def _run(key, code):
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(PROJECT / ".test-data"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_DOTENV_DISABLED": "1",
        "MANUSCRIPT_MODE": "development",
    }
    if key is not None:
        env["SECRET_KEY"] = key
    return subprocess.run([sys.executable, "-B", "-c", code], cwd=PROJECT,
                          env=env, capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("key", [None, "", "   ", "short-synthetic-key"])
def test_missing_or_weak_key_rejects_startup(key):
    result = _run(key, "import app.security")
    assert result.returncode != 0
    assert "Collaboration signing key must contain at least 32 bytes" in result.stderr


def test_valid_key_preserves_access_and_lifecycle_token_checks():
    code = (
        "from app.security import create_access_token, decode_access_token, decode_lifecycle_generation\n"
        "token = create_access_token(7, lifecycle_generation=3)\n"
        "assert decode_access_token(token) == 7\n"
        "assert decode_lifecycle_generation(token, 7) == 3\n"
        "assert decode_lifecycle_generation(token, 8) is None\n"
    )
    result = _run(secrets.token_hex(32), code)
    assert result.returncode == 0, result.stderr
