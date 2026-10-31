import asyncio
import logging

from data.models import init_db
from engine.core import price_scheduler

logging.basicConfig(level=logging.INFO)


def main():
    init_db()
    try:
        asyncio.run(price_scheduler())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
