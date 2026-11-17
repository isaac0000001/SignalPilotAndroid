import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import ScanRun
from app.services.market_data import (
    MarketDataError,
    fetch_forex_candles,
)
from app.signals import (
    Candle,
    analyze_multi_timeframe,
    result_to_dict,
)

logger = logging.getLogger(__name__)

settings = get_settings()

_scan_lock = asyncio.Lock()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _fetch_timeframe(
    symbol: str,
    timeframe: str,
) -> list[Candle]:
    rows = await fetch_forex_candles(
        symbol=symbol,
        interval=timeframe,
        outputsize=120,
    )

    if len(rows) < 60:
        raise MarketDataError(
            f"Insufficient candles for {symbol} at {timeframe}."
        )

    return [
        Candle(
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
        )
        for row in rows
    ]


async def _scan_symbol(
    symbol: str,
    request_delay: float,
) -> dict[str, Any]:
    market_data: dict[str, list[Candle]] = {}

    timeframes = ["4h", "1h", "15min"]

    for index, timeframe in enumerate(timeframes):
        if index > 0:
            await asyncio.sleep(request_delay)

        market_data[timeframe] = await _fetch_timeframe(
            symbol,
            timeframe,
        )

    result = analyze_multi_timeframe(
        market_data=market_data,
        mode="day_trading",
        account_balance=1000.0,
        risk_percent=0.5,
        value_per_price_unit=1.0,
        risk_reward_ratio=2.0,
        symbol=symbol,
    )

    result_data = result_to_dict(result)

    # Broker contract specifications have not yet been verified.
    # Do not publish an estimated position size as reliable.
    result_data["position_size"] = None
    result_data["risk_amount"] = None
    result_data["position_sizing_status"] = (
        "UNVERIFIED_BROKER_CONTRACT_SPECIFICATIONS"
    )

    result_data["live_execution_enabled"] = False

    return result_data


async def run_automatic_scan() -> dict[str, Any]:
    if not settings.AUTOMATION_ENABLED:
        return {
            "status": "disabled",
            "message": "Automatic scanning is disabled.",
        }

    if _scan_lock.locked():
        return {
            "status": "skipped",
            "message": "Another scan is already running.",
        }

    async with _scan_lock:
        started_at = utc_now()

        symbols = list(settings.SCAN_SYMBOLS)
        timeframes = list(settings.SCAN_TIMEFRAMES)

        scan = ScanRun(
            status="RUNNING",
            mode="day_trading",
            symbols=symbols,
            timeframes=timeframes,
            account_balance=Decimal("1000"),
            risk_percent=Decimal("0.5"),
            risk_reward_ratio=Decimal("2"),
            minimum_score=60,
            markets_requested=len(symbols),
            markets_analyzed=0,
            opportunities_found=0,
            markets_failed=0,
            results=[],
            started_at=started_at,
        )

        async with AsyncSessionLocal() as session:
            session.add(scan)
            await session.commit()
            await session.refresh(scan)

            scan_results: list[dict[str, Any]] = []
            opportunities: list[dict[str, Any]] = []
            failures: list[dict[str, str]] = []

            analyzed = 0

            try:
                delay = max(
                    8.0,
                    float(
                        settings.MARKET_DATA_REQUEST_DELAY_SECONDS
                    ),
                )

                for symbol in symbols:
                    try:
                        result = await _scan_symbol(
                            symbol=symbol,
                            request_delay=delay,
                        )

                        analyzed += 1
                        scan_results.append(result)

                        if (
                            result["signal"] in ("BUY", "SELL")
                            and result["score"] >= 60
                        ):
                            opportunities.append(result)

                    except Exception as exc:
                        logger.exception(
                            "Automatic scan failed for %s",
                            symbol,
                        )

                        failures.append({
                            "symbol": symbol,
                            "error": str(exc)[:500],
                        })

                opportunities.sort(
                    key=lambda item: item["score"],
                    reverse=True,
                )

                completed_at = utc_now()

                final_results = {
                    "opportunities": opportunities,
                    "all_results": scan_results,
                    "failures": failures,
                    "live_execution_enabled": False,
                    "position_sizing_verified": False,
                }

                scan.status = (
                    "COMPLETED_WITH_ERRORS"
                    if failures
                    else "COMPLETED"
                )

                scan.markets_analyzed = analyzed
                scan.opportunities_found = len(opportunities)
                scan.markets_failed = len(failures)
                scan.results = final_results
                scan.completed_at = completed_at

                await session.commit()

                return {
                    "scan_id": str(scan.id),
                    "status": scan.status,
                    "started_at": started_at.isoformat(),
                    "completed_at": completed_at.isoformat(),
                    "markets_requested": len(symbols),
                    "markets_analyzed": analyzed,
                    "markets_failed": len(failures),
                    "opportunities_found": len(opportunities),
                    **final_results,
                }

            except Exception as exc:
                await session.rollback()

                logger.exception("Automatic scan failed.")

                async with AsyncSessionLocal() as error_session:
                    failed_scan = await error_session.get(
                        ScanRun,
                        scan.id,
                    )

                    if failed_scan:
                        failed_scan.status = "FAILED"
                        failed_scan.error_message = str(exc)[:2000]
                        failed_scan.completed_at = utc_now()
                        await error_session.commit()

                raise
