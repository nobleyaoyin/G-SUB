"""Run the demo gateway on loopback only."""
import argparse
import os
from pathlib import Path
import sys

project = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-root", required=True)
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
# The project-local legacy Demo is retired; temporary synthetic roots remain
# available to isolated browser tests. The official Demo has its own launcher.
if Path(args.data_root).resolve() == (project / ".demo_data").resolve():
    raise SystemExit("This project-local Demo is retired. Use scripts/run_official_demo.py in Main.")
if not 1 <= args.port <= 65535:
    raise SystemExit("Invalid port")
os.environ["MANUSCRIPT_MODE"] = "demo"
os.environ["MANUSCRIPT_DEMO_ROOT"] = args.data_root
from app.config import DATA_ROOT
from app.demo_gateway import app
import uvicorn

print(f"Demo database: {DATA_ROOT / 'manuscript.db'}", flush=True)
print(f"Demo uploads: {DATA_ROOT / 'uploads'}", flush=True)
uvicorn.run(app, host="127.0.0.1", port=args.port, proxy_headers=False)
