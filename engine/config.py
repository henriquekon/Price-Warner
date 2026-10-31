import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADDONS_DIR = Path(os.getenv("ADDONS_DIR", str(PROJECT_ROOT / "addons"))).resolve()
SCHEDULER_INTERVAL_SECONDS = max(1, int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60")))
