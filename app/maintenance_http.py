"""Optional request participation in the existing cross-process barrier.

This does not protect standalone jobs or non-cooperating filesystem writers.
All application processes must use the same private, stable lock directory.
"""
import logging
import os

from starlette.responses import JSONResponse

from app.maintenance_barrier import MaintenanceActive, MaintenanceBarrier


logger = logging.getLogger(__name__)


class MaintenanceHTTPMiddleware:
    def __init__(self, app):
        self.app = app
        self.directory = os.environ.get("GSUB_MAINTENANCE_ROOT")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.directory or scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        try:
            barrier = MaintenanceBarrier(self.directory)
            participant = barrier.operation()
            participant.__enter__()
        except (MaintenanceActive, OSError, ValueError, RuntimeError):
            logger.warning("Request blocked: maintenance active or coordination unavailable")
            payload = {"error": 1} if scope.get("path", "").startswith("/onlyoffice/callbacks/") else {
                "detail": "The service is temporarily unavailable. Please try again later."
            }
            await JSONResponse(payload, status_code=503, headers={"Retry-After": "30"})(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        finally:
            participant.__exit__(None, None, None)
