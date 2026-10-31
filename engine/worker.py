import asyncio
import logging

from engine.migrations import upgrade
from engine.core import price_scheduler

logging.basicConfig(level=logging.INFO)


def main():
    upgrade()
    try:
        asyncio.run(price_scheduler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
