import uvicorn
import asyncio
from fastapi import FastAPI
from engine.api import router as api_router
from engine.core import price_scheduler
from data.models import init_db

app = FastAPI(title="Price-Warner Server")

app.include_router(api_router)

@app.on_event("startup")
async def on_startup():
    init_db()
    asyncio.create_task(price_scheduler())

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=9873, reload=True)