"""Manual/CI verification for submission checklist items (Application and data)."""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.analysis import (  # noqa: E402
    build_day_series,
    decision_cutoff_for_delivery,
    month_accuracy,
    parse_ts,
)
from app.elexon import load_cache  # noqa: E402

ELEXON = "https://data.elexon.co.uk/bmrs/api/v1"


def get(url: str):
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    checks = []

    # 1) Official endpoint shapes
    fuelhh = get(
        f"{ELEXON}/datasets/FUELHH/stream"
        "?settlementDateFrom=2026-01-15&settlementDateTo=2026-01-15&fuelType=WIND"
    )
    windfor = get(
        f"{ELEXON}/datasets/WINDFOR/stream"
        "?publishDateTimeFrom=2026-01-14T07:00:00Z&publishDateTimeTo=2026-01-14T08:00:00Z"
    )
    ok_fuel = (
        len(fuelhh) == 48
        and all(r.get("fuelType") == "WIND" for r in fuelhh)
        and {"startTime", "generation", "settlementPeriod"} <= set(fuelhh[0])
    )
    ok_wind = len(windfor) > 0 and {"startTime", "publishTime", "generation"} <= set(
        windfor[0]
    )
    checks.append(("Elexon FUELHH/WINDFOR endpoint shapes", ok_fuel and ok_wind))

    actuals, forecasts, _ = load_cache()
    acc = month_accuracy(forecasts, actuals, date(2026, 1, 1), date(2026, 1, 31))

    # 2) Vintage selection
    viol = 0
    for day_i in range(1, 32):
        d = date(2026, 1, day_i)
        cutoff = decision_cutoff_for_delivery(d)
        series = build_day_series(forecasts, actuals, d)
        for point in series["points"]:
            later = [
                row
                for row in forecasts
                if row["startTime"] == point["startTime"]
                and parse_ts(row["publishTime"]) <= cutoff
                and parse_ts(row["publishTime"]) > parse_ts(point["publishTime"])
            ]
            viol += len(later)
    checks.append(("Forecast vintage ≤ D−1 cutoff (0 violations)", viol == 0))

    # 3) 744 from half-hourly
    half = sum(1 for r in actuals if r.get("fuelType") == "WIND")
    checks.append(
        (
            "744 hours from 1488 half-hours (100% matched)",
            half == 1488
            and acc["coverage"]["matchedHours"] == 744
            and acc["coverage"]["coveragePct"] == 100.0,
        )
    )

    # 4) Independent metrics
    errors = []
    for day_i in range(1, 32):
        series = build_day_series(forecasts, actuals, date(2026, 1, day_i))
        errors.extend(p["errorMw"] for p in series["points"] if p["errorMw"] is not None)
    n = len(errors)
    mae = round(sum(abs(e) for e in errors) / n, 1)
    rmse = round((sum(e * e for e in errors) / n) ** 0.5, 1)
    bias = round(sum(errors) / n, 1)
    checks.append(
        (
            f"Independent metrics MAE={mae} RMSE={rmse} bias={bias}",
            mae == 2142.1 and rmse == 2611.7 and bias == 1851.9 and n == 744,
        )
    )

    # 5) Daily MAE same rules
    mean_daily = round(sum(d["maeMw"] for d in acc["daily"]) / len(acc["daily"]), 1)
    checks.append(
        (
            "Daily MAE bars use same hourly aggregation as overall",
            mean_daily == acc["overall"]["maeMw"] and all(d["n"] == 24 for d in acc["daily"]),
        )
    )

    print("Submission checklist — Application and data")
    failed = 0
    for name, ok in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name}")
        if not ok:
            failed += 1
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
