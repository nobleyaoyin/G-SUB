"""Start the designated Stable Demo using its existing private data root."""
import os
import shlex
import stat
from pathlib import Path

main = Path(__file__).resolve().parent.parent
stable = main.parent / "Manuscript-Stable-Demo"
root = stable / ".demo_data"
python = stable / ".venv" / "bin" / "python"
runner = stable / "scripts" / "run_demo.py"
if not stable.is_dir() or stable.is_symlink() or not root.is_dir() or root.is_symlink():
    raise SystemExit("Official Stable Demo or its data root is missing or unsafe.")
for item in (root / "accounts.json", root / "manuscript.db", root / "jwt.key", root / "uploads"):
    if item.is_symlink() or not item.exists():
        raise SystemExit("Official Stable Demo data is missing or unsafe; no fallback was selected.")
if not python.is_file() or not runner.is_file() or not (stable / "frontend" / "dist" / "index.html").is_file():
    raise SystemExit("Official Stable Demo runtime or frontend build is missing.")
# Load only the private, explicitly named ONLYOFFICE settings. Never overwrite
# externally supplied credentials or print them; absence keeps the feature off.
settings = stable / ".onlyoffice-stable.env"
if settings.exists():
    if settings.is_symlink() or not settings.is_file() or settings.stat().st_nlink != 1 or stat.S_IMODE(settings.stat().st_mode) & 0o077:
        raise SystemExit("ONLYOFFICE settings file must be private and non-symlinked.")
    allowed = {"GSUB_ONLYOFFICE_ENABLED", "GSUB_ONLYOFFICE_SECRET", "GSUB_ONLYOFFICE_SERVER_ORIGIN", "GSUB_ONLYOFFICE_APP_ORIGIN"}
    for line in settings.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key not in allowed:
            raise SystemExit("Unsupported ONLYOFFICE settings entry.")
        try:
            parts = shlex.split(value, comments=False, posix=True)
        except ValueError:
            raise SystemExit("Invalid ONLYOFFICE settings entry.") from None
        if len(parts) != 1:
            raise SystemExit("Invalid ONLYOFFICE settings entry.")
        os.environ.setdefault(key, parts[0])
# The official gateway mounts its backend at /api, unlike direct Uvicorn.
if os.environ.get("GSUB_ONLYOFFICE_ENABLED") == "1":
    os.environ["GSUB_ONLYOFFICE_APP_ORIGIN"] = "http://host.docker.internal:8765/api"
os.chdir(stable)
os.execv(str(python), [str(python), str(runner), "--data-root", str(root), "--port", "8765"])
