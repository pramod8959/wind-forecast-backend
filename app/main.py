from __future__ import annotations

from datetime import date
from functools import lru_cache

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .analysis import build_day_series, month_accuracy
from .config import (
    DECISION_CUTOFF_HOUR_UTC,
    DECISION_CUTOFF_MINUTE_UTC,
    DELIVERY_MONTH_END,
    DELIVERY_MONTH_START,
)
from .elexon import load_cache

app = FastAPI(
    title="GB Wind Day-Ahead Briefing",
    description="Decision-time wind forecasts and accuracy for UK day-ahead procurement (January 2026).",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _data():
    return load_cache()


def _parse_day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(400, f"Invalid date: {value}") from exc


def _ensure_in_scope(d: date) -> None:
    start = date.fromisoformat(DELIVERY_MONTH_START)
    end = date.fromisoformat(DELIVERY_MONTH_END)
    if d < start or d > end:
        raise HTTPException(
            400,
            f"Delivery date must be a January 2026 purchase-decision day "
            f"({DELIVERY_MONTH_START} … {DELIVERY_MONTH_END})",
        )


@app.get("/api/health")
def health():
    try:
        actuals, forecasts, meta = _data()
        return {
            "status": "ok",
            "actualsRows": len(actuals),
            "forecastRows": len(forecasts),
            "meta": meta,
        }
    except FileNotFoundError as exc:
        return {"status": "degraded", "error": str(exc)}


@app.get("/api/meta")
def meta():
    _, _, cached = _data()
    return {
        **cached,
        "decisionCutoff": {
            "hourUtc": DECISION_CUTOFF_HOUR_UTC,
            "minuteUtc": DECISION_CUTOFF_MINUTE_UTC,
            "timezone": "UTC",
            "rule": (
                "For delivery day D, use the latest WINDFOR published at or before "
                f"{DECISION_CUTOFF_HOUR_UTC:02d}:{DECISION_CUTOFF_MINUTE_UTC:02d} UTC "
                "on the decision date D−1."
            ),
        },
        "scope": {
            "deliveryFrom": DELIVERY_MONTH_START,
            "deliveryTo": DELIVERY_MONTH_END,
            "fuel": "WIND",
            "sources": ["FUELHH", "WINDFOR"],
            "note": (
                "Pilot scope is January 2026 delivery days only. "
                "Decisions for those days were made on the preceding day."
            ),
        },
    }


@app.get("/api/briefing/{delivery_date}")
def briefing(delivery_date: str):
    """Decision-time wind forecast vs full-day historical actuals for one January 2026 day."""
    d = _parse_day(delivery_date)
    _ensure_in_scope(d)
    actuals, forecasts, _ = _data()
    series = build_day_series(forecasts, actuals, d)
    series["dataSource"] = "cache"
    return series


@app.get("/api/accuracy")
def accuracy(
    date_from: str = Query(default=DELIVERY_MONTH_START, alias="from"),
    date_to: str = Query(default=DELIVERY_MONTH_END, alias="to"),
):
    start = _parse_day(date_from)
    end = _parse_day(date_to)
    _ensure_in_scope(start)
    _ensure_in_scope(end)
    if start > end:
        raise HTTPException(400, "`from` must be <= `to`")
    actuals, forecasts, _ = _data()
    return month_accuracy(forecasts, actuals, start, end)
