from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "inventory-service"}


@router.get("/health/ready")
async def readiness() -> dict[str, str]:
    return {"status": "ready"}
