"""Decision-time forecast selection and accuracy metrics for GB day-ahead wind."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any

from .config import DECISION_CUTOFF_HOUR_UTC, DECISION_CUTOFF_MINUTE_UTC

EXPECTED_HOURS = 24
EXPECTED_HALF_HOURS = 48


def parse_ts(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decision_cutoff_for_delivery(delivery: date) -> datetime:
    """Gate for buying delivery-day power: morning of D-1 before day-ahead auctions."""
    d_minus_1 = delivery - timedelta(days=1)
    return datetime(
        d_minus_1.year,
        d_minus_1.month,
        d_minus_1.day,
        DECISION_CUTOFF_HOUR_UTC,
        DECISION_CUTOFF_MINUTE_UTC,
        tzinfo=timezone.utc,
    )


def delivery_hourly_starts(delivery: date) -> list[datetime]:
    """24 hourly timestamps for a calendar delivery day (UTC; January is GMT)."""
    start = datetime(delivery.year, delivery.month, delivery.day, tzinfo=timezone.utc)
    return [start + timedelta(hours=h) for h in range(24)]


def filter_actuals_for_delivery(
    actual_rows: list[dict[str, Any]], delivery: date
) -> list[dict[str, Any]]:
    day = delivery.isoformat()
    return [
        row
        for row in actual_rows
        if row.get("fuelType", "WIND") == "WIND" and row.get("settlementDate") == day
    ]


def aggregate_actuals_to_hourly(actual_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Average the two FUELHH (30-min) periods that sit inside each clock hour."""
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in actual_rows:
        ts = parse_ts(row["startTime"])
        hour_start = ts.replace(minute=0, second=0, microsecond=0)
        buckets[to_iso(hour_start)].append(float(row["generation"]))
    return {key: mean(values) for key, values in buckets.items()}


def select_decision_time_forecasts(
    forecast_rows: list[dict[str, Any]],
    delivery: date,
) -> list[dict[str, Any]]:
    """
    For each hourly startTime on delivery day D, pick the latest WINDFOR row with
    publishTime <= decision cutoff on D-1.
    """
    cutoff = decision_cutoff_for_delivery(delivery)
    targets = {to_iso(ts) for ts in delivery_hourly_starts(delivery)}

    best: dict[str, dict[str, Any]] = {}
    for row in forecast_rows:
        start = row["startTime"]
        if start not in targets:
            continue
        pub = parse_ts(row["publishTime"])
        if pub > cutoff:
            continue
        prev = best.get(start)
        if prev is None or parse_ts(row["publishTime"]) > parse_ts(prev["publishTime"]):
            best[start] = row

    series = []
    for ts in delivery_hourly_starts(delivery):
        key = to_iso(ts)
        row = best.get(key)
        if not row:
            continue
        series.append(
            {
                "startTime": key,
                "forecastMw": float(row["generation"]),
                "publishTime": row["publishTime"],
                "decisionCutoff": to_iso(cutoff),
            }
        )
    return series


def build_day_series(
    forecast_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    delivery: date,
) -> dict[str, Any]:
    cutoff = decision_cutoff_for_delivery(delivery)
    forecasts = select_decision_time_forecasts(forecast_rows, delivery)
    day_actuals = filter_actuals_for_delivery(actual_rows, delivery)
    hourly_actuals = aggregate_actuals_to_hourly(day_actuals)

    points = []
    errors: list[float] = []
    missing_actuals: list[str] = []
    missing_forecasts: list[str] = []
    forecast_by_start = {row["startTime"]: row for row in forecasts}

    for ts in delivery_hourly_starts(delivery):
        key = to_iso(ts)
        fc = forecast_by_start.get(key)
        actual = hourly_actuals.get(key)
        if fc is None:
            missing_forecasts.append(key)
            continue
        error = (fc["forecastMw"] - actual) if actual is not None else None
        if actual is None:
            missing_actuals.append(key)
        if error is not None:
            errors.append(error)
        points.append({**fc, "actualMw": actual, "errorMw": error})

    n_over = sum(1 for error in errors if error > 0)
    n_under = sum(1 for error in errors if error < 0)
    n_zero = sum(1 for error in errors if error == 0)

    return {
        "deliveryDate": delivery.isoformat(),
        "decisionDate": (delivery - timedelta(days=1)).isoformat(),
        "decisionCutoff": to_iso(cutoff),
        "timezone": "UTC",
        "publishTimesUsed": sorted({point["publishTime"] for point in points}),
        "points": points,
        "metrics": compute_metrics(errors) if errors else None,
        "coverage": {
            "expectedHours": EXPECTED_HOURS,
            "forecastHours": len(forecasts),
            "actualHalfHours": len(day_actuals),
            "expectedHalfHours": EXPECTED_HALF_HOURS,
            "matchedHours": len(errors),
            "missingForecastHours": missing_forecasts,
            "missingActualHours": missing_actuals,
            "nOverforecast": n_over,
            "nUnderforecast": n_under,
            "nExact": n_zero,
        },
        "methodology": {
            "units": "MW",
            "forecastResolution": "hourly (WINDFOR native)",
            "actualResolution": "half-hourly (FUELHH native)",
            "joinResolution": "hourly; actual = mean of the two 30-minute FUELHH periods in that hour",
            "matchKey": "startTime (hour beginning, UTC)",
            "decisionRule": (
                f"Latest WINDFOR with publishTime <= {to_iso(cutoff)} "
                f"(09:00 UTC on D−1, before typical GB day-ahead gate)."
            ),
            "metricsNote": (
                "MAE and bias use matched hours only. If every error has the same sign, "
                "MAE equals |bias|."
            ),
            "scopeNote": (
                "Wind forecast error quantifies renewable uncertainty. It does not by itself "
                "say how much power to buy — that also needs demand and other supply, which "
                "are out of scope."
            ),
        },
    }


def compute_metrics(errors: list[float]) -> dict[str, Any]:
    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = (sum(e * e for e in errors) / n) ** 0.5
    bias = sum(errors) / n
    return {
        "n": n,
        "maeMw": round(mae, 1),
        "rmseMw": round(rmse, 1),
        "biasMw": round(bias, 1),
        "sameSign": abs(round(mae, 1) - abs(round(bias, 1))) < 0.05,
    }


def month_accuracy(
    forecast_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    start: date,
    end: date,
) -> dict[str, Any]:
    daily = []
    all_errors: list[float] = []
    missing: list[dict[str, Any]] = []
    day = start
    while day <= end:
        series = build_day_series(forecast_rows, actual_rows, day)
        coverage = series["coverage"]
        if coverage["missingForecastHours"] or coverage["missingActualHours"]:
            missing.append(
                {
                    "deliveryDate": series["deliveryDate"],
                    "missingForecastHours": coverage["missingForecastHours"],
                    "missingActualHours": coverage["missingActualHours"],
                    "actualHalfHours": coverage["actualHalfHours"],
                }
            )
        if series["metrics"]:
            daily.append(
                {
                    "deliveryDate": series["deliveryDate"],
                    "decisionDate": series["decisionDate"],
                    "decisionCutoff": series["decisionCutoff"],
                    **series["metrics"],
                    "matchedHours": coverage["matchedHours"],
                    "publishTimesUsed": series["publishTimesUsed"],
                    "nOverforecast": coverage["nOverforecast"],
                    "nUnderforecast": coverage["nUnderforecast"],
                }
            )
            for point in series["points"]:
                if point["errorMw"] is not None:
                    all_errors.append(point["errorMw"])
        day += timedelta(days=1)

    overall = compute_metrics(all_errors) if all_errors else None
    expected = ((end - start).days + 1) * EXPECTED_HOURS
    matched = len(all_errors)
    sample_method = (
        build_day_series(forecast_rows, actual_rows, start).get("methodology")
        if start <= end
        else None
    )
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "decisionRule": (
            f"For delivery day D, use the latest WINDFOR with publishTime <= "
            f"{DECISION_CUTOFF_HOUR_UTC:02d}:{DECISION_CUTOFF_MINUTE_UTC:02d} UTC on D−1 "
            "(configurable assumption, before typical GB day-ahead gate ~09:20–09:50 GMT)."
        ),
        "methodology": {
            **(sample_method or {}),
            "chartMetric": "dailyMaeMw",
            "chartDefinition": (
                "Each bar is that delivery day’s MAE across its matched hourly periods "
                "(mean of |forecast − actual| for hours with both values)."
            ),
            "biasDefinition": "mean(forecast − actual) over matched hours; positive = over-forecast",
            "aggregation": (
                f"FUELHH supplies {EXPECTED_HALF_HOURS} half-hours/day; metrics are computed on "
                f"{EXPECTED_HOURS} hourly means/day (not on 1,488 settlement periods)."
            ),
        },
        "overall": overall,
        "coverage": {
            "expectedMatchedHours": expected,
            "matchedHours": matched,
            "coveragePct": round(100.0 * matched / expected, 1) if expected else 0.0,
            "actualHalfHourRows": sum(
                1
                for row in actual_rows
                if start.isoformat()
                <= row.get("settlementDate", "")
                <= end.isoformat()
            ),
            "daysWithGaps": missing,
        },
        "daily": daily,
    }
