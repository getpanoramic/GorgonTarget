import logging
import sys
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send
from .utils import logger
from .routes import series, episodes, history, system, command, blocklist

# ---------------------------------------------------------------------------
# PATH NORMALIZATION MIDDLEWARE (Fixes double slashes)
# ---------------------------------------------------------------------------
class PathNormalizationMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            logger.debug(f"Incoming path: {path}")
            new_path = path.replace("//", "/")
            while "/api/api/" in new_path:
                new_path = new_path.replace("/api/api/", "/api/")
            while "/api/v3/api/v3/" in new_path:
                new_path = new_path.replace("/api/v3/api/v3/", "/api/v3/")
            scope["path"] = new_path.lower()
            logger.debug(f"Normalized path: {new_path}")
        await self.app(scope, receive, send)

# ---------------------------------------------------------------------------
# APP INITIALIZATION
# ---------------------------------------------------------------------------
app = FastAPI(title="GorgonTarget Stateless Proxy", version="3.6.0")
app.add_middleware(PathNormalizationMiddleware)

# Global Exception Handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"message": "Internal Server Error"}
    )

# Register Routers
app.include_router(series.router)
app.include_router(episodes.router)
app.include_router(history.router)
app.include_router(system.router)
app.include_router(command.router)
app.include_router(blocklist.router)

@app.get("/")
async def root_index():
    return {"status": "running", "service": "GorgonTarget Stateless Proxy"}
