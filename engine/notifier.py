import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
from engine.config import NOTIFICATION_LOG_PATH

LOG_FILE = NOTIFICATION_LOG_PATH


class Notifier:
    def send(self, message: str):
        logger.info("Notification generated: %s", message)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
