"""The Rahmat webhook ASGI router and application.

Serves POST /rhmt/callback (and /callback) for Rahmat payment notifications.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request, status
from starlette.responses import JSONResponse

from bayram.logging import get_logger
from bayram.rhmt.service import RhmtWebhookService

__all__ = ["build_rhmt_router", "create_rhmt_app"]

_LOG = get_logger(__name__)


def build_rhmt_router(service: RhmtWebhookService | None = None) -> APIRouter:
    """Build an APIRouter handling Rahmat callbacks."""
    router = APIRouter(prefix="/rhmt", tags=["rhmt"])

    @router.post("/callback", status_code=status.HTTP_200_OK)
    @router.post("/callback/", status_code=status.HTTP_200_OK)
    async def rhmt_callback(request: Request) -> JSONResponse:
        svc = service
        if svc is None:
            svc = getattr(request.app.state, "rhmt_service", None)
        if svc is None:
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={"success": False, "error": "rhmt service not configured"},
            )
        try:
            payload = await request.json()
        except Exception as exc:
            _LOG.warning("invalid json in rhmt callback request", extra={"error": str(exc)})
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"success": False, "error": "invalid json body"},
            )

        status_code, body = await svc.handle_callback(payload)
        return JSONResponse(status_code=status_code, content=body)

    return router


def create_rhmt_app(service: RhmtWebhookService | None = None) -> FastAPI:
    """Create a standalone FastAPI app for Rahmat callbacks."""
    app = FastAPI(title="Bayram Rahmat Webhook Gateway", docs_url=None, redoc_url=None)
    app.include_router(build_rhmt_router(service))
    return app
