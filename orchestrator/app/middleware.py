from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.services.instance_auth import get_effective_api_key


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Require X-API-Key when an API key is configured (env or dashboard)."""

    EXEMPT = {
        "/health",
        "/docs",
        "/openapi.json",
        "/redoc",
        "/api/settings/public",
        "/api/settings/setup",
    }
    EXEMPT_PREFIXES = ("/ui", "/ws/")

    async def dispatch(self, request: Request, call_next):
        api_key = get_effective_api_key()
        if not api_key:
            return await call_next(request)

        path = request.url.path
        if path in self.EXEMPT or any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)

        key = request.headers.get("X-API-Key")
        if key != api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})

        return await call_next(request)
