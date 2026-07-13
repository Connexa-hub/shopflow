from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "sales-service"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}
