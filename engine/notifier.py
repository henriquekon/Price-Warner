import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
LOG_FILE = Path(__file__).resolve().parent.parent / "notifications.log"


class Notifier:
    def send(self, message: str):
        logger.info("Notification generated: %s", message)
        with LOG_FILE.open("a", encoding="utf-8") as file:
            file.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
