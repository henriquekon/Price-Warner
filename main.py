import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from engine.migrations import upgrade
from engine.api import router as api_router
from engine.auth_api import router as auth_router
from engine.core import price_scheduler
from engine.config import RUN_SCHEDULER

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    upgrade()
    task = asyncio.create_task(price_scheduler()) if RUN_SCHEDULER else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.info("Price scheduler stopped")


app = FastAPI(title="Price-Warner Server", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=9873, reload=True)
