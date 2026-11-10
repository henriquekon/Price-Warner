import asyncio
import logging
import os
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request

from engine.migrations import upgrade
from engine.api import router as api_router
from engine.auth_api import router as auth_router
from engine.notifications_api import router as notifications_router
from engine.dashboard_api import router as dashboard_router
from engine.alerts_api import router as alerts_router
from engine.discovery_api import router as discovery_router
from engine.product_details_api import router as product_details_router
from engine.image_cache import router as image_router
from engine.tags import router as tags_router
from engine.health_api import router as health_router
from engine.core import price_scheduler
from engine.config import RUN_SCHEDULER

log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
logging.basicConfig(level=getattr(logging, log_level, logging.INFO))
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


app = FastAPI(title="Price-Warner Server", version="1.0.0-beta.5", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"
    return response
app.include_router(auth_router)
app.include_router(notifications_router)
app.include_router(dashboard_router)
app.include_router(alerts_router)
app.include_router(discovery_router)
app.include_router(product_details_router)
api_router.routes[:] = [route for route in api_router.routes if route.path != "/"]
app.include_router(api_router)
app.include_router(image_router)
app.include_router(tags_router)
app.include_router(health_router)

frontend_dist = Path(__file__).resolve().parent / "frontend" / "dist"
if frontend_dist.joinpath("index.html").is_file():
    app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index():
        return FileResponse(frontend_dist / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def frontend_not_built():
        return HTMLResponse("<h1>Price-Warner frontend not built</h1><p>Build the frontend or run Vite on port 5173.</p>", status_code=503)


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=9873, reload=True)
