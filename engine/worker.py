import asyncio
import logging
import os

from engine.migrations import upgrade
from engine.core import price_scheduler

log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))


def main():
    upgrade()
    try:
        asyncio.run(price_scheduler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
