"""Thin client for Elexon Insights BMRS dataset stream endpoints."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import (
    ACTUALS_PATH,
    ELEXON_BASE,
    FORECAST_PUBLISH_FROM,
    FORECAST_PUBLISH_TO,
    FORECASTS_PATH,
    META_PATH,
    DELIVERY_MONTH_END,
    DELIVERY_MONTH_START,
)


def _get(path: str, params: dict[str, str]) -> list[dict[str, Any]]:
    url = f"{ELEXON_BASE}{path}?{urlencode(params)}"
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    if not isinstance(data, list):
        raise RuntimeError(f"Unexpected response from {url}: {data}")
    return data


def fetch_actuals(settlement_from: str, settlement_to: str) -> list[dict[str, Any]]:
    return _get(
        "/datasets/FUELHH/stream",
        {
            "settlementDateFrom": settlement_from,
            "settlementDateTo": settlement_to,
            "fuelType": "WIND",
        },
    )


def fetch_forecasts(publish_from: str, publish_to: str) -> list[dict[str, Any]]:
    return _get(
        "/datasets/WINDFOR/stream",
        {
            "publishDateTimeFrom": publish_from,
            "publishDateTimeTo": publish_to,
        },
    )


def _chunk_dates(start: date, end: date, days: int) -> list[tuple[date, date]]:
    chunks = []
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=days - 1), end)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)
    return chunks


def download_and_cache(data_dir: Path | None = None) -> dict[str, Any]:
    """Download Jan 2026 actuals + relevant WINDFOR publishes into local JSON cache."""
    data_dir = data_dir or ACTUALS_PATH.parent
    data_dir.mkdir(parents=True, exist_ok=True)

    start = date.fromisoformat(DELIVERY_MONTH_START)
    end = date.fromisoformat(DELIVERY_MONTH_END)

    actuals: list[dict[str, Any]] = []
    for a, b in _chunk_dates(start, end, 7):
        chunk = fetch_actuals(a.isoformat(), b.isoformat())
        actuals.extend(chunk)
        print(f"actuals {a}..{b}: {len(chunk)} rows")

    # Forecasts in weekly publish windows to keep responses manageable
    forecasts: list[dict[str, Any]] = []
    pub_start = date.fromisoformat(FORECAST_PUBLISH_FROM[:10])
    pub_end = date.fromisoformat(FORECAST_PUBLISH_TO[:10])
    for a, b in _chunk_dates(pub_start, pub_end, 3):
        pf = f"{a.isoformat()}T00:00:00Z"
        pt = f"{b.isoformat()}T23:59:59Z"
        chunk = fetch_forecasts(pf, pt)
        forecasts.extend(chunk)
        print(f"forecasts publish {a}..{b}: {len(chunk)} rows")

    ACTUALS_PATH.write_text(json.dumps(actuals))
    FORECASTS_PATH.write_text(json.dumps(forecasts))
    meta = {
        "actualsRows": len(actuals),
        "forecastRows": len(forecasts),
        "deliveryFrom": DELIVERY_MONTH_START,
        "deliveryTo": DELIVERY_MONTH_END,
        "forecastPublishFrom": FORECAST_PUBLISH_FROM,
        "forecastPublishTo": FORECAST_PUBLISH_TO,
        "source": ELEXON_BASE,
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print("wrote", ACTUALS_PATH, FORECASTS_PATH, META_PATH)
    return meta


def load_cache() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not ACTUALS_PATH.exists() or not FORECASTS_PATH.exists():
        raise FileNotFoundError(
            "Cached data missing. Run: python -m scripts.etl  (from backend/)"
        )
    actuals = json.loads(ACTUALS_PATH.read_text())
    forecasts = json.loads(FORECASTS_PATH.read_text())
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    return actuals, forecasts, meta


def fetch_live_day(delivery: date) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pull actuals + nearby WINDFOR publishes for one delivery day (e.g. today)."""
    # Decision is D-1 morning; pull publishes from D-2 through D to cover the cutoff vintage.
    pub_from = (delivery - timedelta(days=2)).isoformat()
    pub_to = delivery.isoformat()
    forecasts = fetch_forecasts(f"{pub_from}T00:00:00Z", f"{pub_to}T23:59:59Z")
    actuals = fetch_actuals(delivery.isoformat(), delivery.isoformat())
    return actuals, forecasts


def in_jan_cache(delivery: date) -> bool:
    start = date.fromisoformat(DELIVERY_MONTH_START)
    end = date.fromisoformat(DELIVERY_MONTH_END)
    return start <= delivery <= end
