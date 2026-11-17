import secrets
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ScanRun
from app.services.automatic_scanner import run_automatic_scan

router = APIRouter(
    prefix="/automation",
    tags=["Automatic Scanning"],
)

settings = get_settings()


def verify_automation_token(
    authorization: str | None,
) -> None:
    configured_token = settings.AUTOMATION_TOKEN

    if configured_token is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Automation token has not been configured.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid automation token is required.",
        )

    supplied_token = authorization.removeprefix("Bearer ").strip()

    expected_token = configured_token.get_secret_value()

    if not secrets.compare_digest(
        supplied_token,
        expected_token,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid automation token.",
        )


@router.post("/run-now")
async def run_now(
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    verify_automation_token(authorization)

    try:
        return await run_automatic_scan()

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Automatic scan failed. Check the server logs.",
        )


@router.get("/status")
async def automation_status() -> dict[str, Any]:
    return {
        "automation_enabled": settings.AUTOMATION_ENABLED,
        "interval_minutes": settings.AUTOMATION_INTERVAL_MINUTES,
        "live_trading_enabled": False,
        "symbols": settings.SCAN_SYMBOLS,
        "timeframes": settings.SCAN_TIMEFRAMES,
        "minimum_signal_score": settings.DEFAULT_MINIMUM_SIGNAL_SCORE,
        "risk_percent": settings.DEFAULT_RISK_PERCENT,
    }


@router.get("/history")
async def scan_history(
    limit: int = 20,
) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 100.",
        )

    async with AsyncSessionLocal() as session:
        query = (
            select(ScanRun)
            .order_by(ScanRun.started_at.desc())
            .limit(limit)
        )

        result = await session.execute(query)
        scans = result.scalars().all()

        return {
            "count": len(scans),
            "scans": [
                {
                    "id": str(scan.id),
                    "status": scan.status,
                    "mode": scan.mode,
                    "markets_requested": scan.markets_requested,
                    "markets_analyzed": scan.markets_analyzed,
                    "opportunities_found": scan.opportunities_found,
                    "markets_failed": scan.markets_failed,
                    "started_at": (
                        scan.started_at.isoformat()
                        if scan.started_at
                        else None
                    ),
                    "completed_at": (
                        scan.completed_at.isoformat()
                        if scan.completed_at
                        else None
                    ),
                    "results": scan.results,
                    "error_message": scan.error_message,
                }
                for scan in scans
            ],
        }
