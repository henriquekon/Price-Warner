import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ADDONS_DIR = Path(os.getenv("ADDONS_DIR", str(PROJECT_ROOT / "addons"))).resolve()
SCHEDULER_INTERVAL_SECONDS = max(1, int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60")))
RUN_SCHEDULER = os.getenv("RUN_SCHEDULER", "true").strip().lower() in {"1", "true", "yes", "on"}
NOTIFICATION_LOG_PATH = Path(os.getenv("NOTIFICATION_LOG_PATH", str(PROJECT_ROOT / "notifications.log")))
