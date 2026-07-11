from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe — used by Docker healthcheck and orchestrators."""
    return {"status": "ok", "service": "auth-service"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    """Readiness probe. Extended in Phase 2+ to check DB/Redis connectivity."""
    return {"status": "ready"}
