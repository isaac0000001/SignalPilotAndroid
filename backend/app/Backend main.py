from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(
    title="SignalPilot Pro API",
    description="Personal FX/CFD trading engine development API",
    version="0.1.0",
)

# Development account only.
# This in-memory account resets when the server restarts.
account = {
    "account_id": "SP-DEMO-001",
    "currency": "USD",
    "initial_balance": 1000.00,
    "balance": 1000.00,
    "equity": 1000.00,
    "open_positions": [],
    "trade_history": [],
}

account_lock = Lock()


class RiskRequest(BaseModel):
    balance: float = Field(gt=0, le=1_000_000_000)
    risk_percent: float = Field(gt=0, le=100)
    stop_distance: float = Field(gt=0, le=1_000_000)


class SimulatedOrderRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
    side: str
    quantity: float = Field(gt=0, le=1_000_000)
    entry_price: float = Field(gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profit: float | None = Field(default=None, gt=0)


@app.get("/")
def home():
    return {
        "application": "SignalPilot Pro",
        "status": "running",
        "mode": "simulation_only",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": "signalpilot-api",
    }


@app.get("/account")
def get_account():
    with account_lock:
        return {
            "account_id": account["account_id"],
            "currency": account["currency"],
            "initial_balance": account["initial_balance"],
            "balance": account["balance"],
            "equity": account["equity"],
            "open_positions": len(account["open_positions"]),
            "mode": "DEMO",
        }


@app.post("/risk/calculate")
def calculate_risk(request: RiskRequest):
    risk_amount = request.balance * request.risk_percent / 100
    simplified_units = risk_amount / request.stop_distance

    return {
        "balance": request.balance,
        "risk_percent": request.risk_percent,
        "maximum_planned_loss": round(risk_amount, 2),
        "stop_distance": request.stop_distance,
        "simplified_units": round(simplified_units, 6),
        "note": (
            "Simplified calculation only. This is not a broker-ready lot size. "
            "Actual sizing requires instrument contract specifications, "
            "pip or tick value, account currency and conversion rates."
        ),
    }


@app.post("/orders/simulate")
def simulate_order(request: SimulatedOrderRequest):
    side = request.side.upper()

    if side not in ("BUY", "SELL"):
        raise HTTPException(
            status_code=400,
            detail="Side must be BUY or SELL.",
        )

    if request.stop_loss is not None:
        if side == "BUY" and request.stop_loss >= request.entry_price:
            raise HTTPException(
                status_code=400,
                detail="A BUY stop loss must be below the entry price.",
            )
        if side == "SELL" and request.stop_loss <= request.entry_price:
            raise HTTPException(
                status_code=400,
                detail="A SELL stop loss must be above the entry price.",
            )

    if request.take_profit is not None:
        if side == "BUY" and request.take_profit <= request.entry_price:
            raise HTTPException(
                status_code=400,
                detail="A BUY take profit must be above the entry price.",
            )
        if side == "SELL" and request.take_profit >= request.entry_price:
            raise HTTPException(
                status_code=400,
                detail="A SELL take profit must be below the entry price.",
            )

    order = {
        "order_id": str(uuid4()),
        "symbol": request.symbol.upper(),
        "side": side,
        "quantity": request.quantity,
        "entry_price": request.entry_price,
        "stop_loss": request.stop_loss,
        "take_profit": request.take_profit,
        "status": "SIMULATED",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    with account_lock:
        account["trade_history"].append(order)

    return {
        "message": "Simulated order created. No broker was contacted.",
        "order": order,
    }


@app.get("/orders")
def list_orders():
    with account_lock:
        return {
            "mode": "DEMO",
            "orders": list(account["trade_history"]),
        }
