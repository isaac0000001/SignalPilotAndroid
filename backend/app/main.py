from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import close_database
from app.api.routes import router as main_router
from app.api.automation import router as automation_router


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_database()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "SignalPilot Pro personal trading backend. "
        "Live trading execution is disabled."
    ),
    lifespan=lifespan,
)

app.include_router(
    main_router,
    prefix=settings.API_PREFIX,
)

app.include_router(
    automation_router,
    prefix=settings.API_PREFIX,
)


@app.get("/")
async def root():
    return {
        "application": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
        "live_trading_enabled": False,
    }
