import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, sessions, uploads
from app.services.firebase import init_firebase
from app.logger import get_logger, setup_logging

def create_app() -> FastAPI:
    """
    Crea la app ASGI (FastAPI) lista para `uvicorn app.main:app`.

    Firebase se inicializa en `lifespan` (startup) para evitar side-effects
    al importar el módulo. En producción, usa `FIREBASE_CREDENTIALS_B64`.
    """
    settings = get_settings()
    setup_logging()
    logger = get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting backend (env=%s)", settings.app_env)
        init_firebase()  # Usa Settings.resolved_firebase_credentials_path()
        logger.info("Startup complete")
        yield

    fastapi_app = FastAPI(
        title="Robonet Sensor Backend",
        version="0.1.0",
        description="Backend para streaming de video e IMU a Cloudflare R2",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # En producción: especifica los dominios permitidos
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    fastapi_app.include_router(auth.router, prefix="/auth", tags=["auth"])
    fastapi_app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    fastapi_app.include_router(uploads.router, prefix="/sessions", tags=["uploads"])

    @fastapi_app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok", "env": settings.app_env}

    return fastapi_app


# Exponemos la app ASGI para uvicorn.
app = create_app()


def start() -> None:
    """Entrypoint para `serve` en pyproject.toml."""
    settings = get_settings()
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.app_env == "development",
    )


if __name__ == "__main__":
    start()
