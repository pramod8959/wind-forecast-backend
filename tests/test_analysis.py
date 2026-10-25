"""Unit tests for decision-time forecast selection and accuracy metrics."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.analysis import (
    aggregate_actuals_to_hourly,
    build_day_series,
    compute_metrics,
    decision_cutoff_for_delivery,
    month_accuracy,
    parse_ts,
    select_decision_time_forecasts,
    to_iso,
)


def test_decision_cutoff_is_0900_utc_on_d_minus_1():
    cutoff = decision_cutoff_for_delivery(date(2026, 1, 15))
    assert cutoff == datetime(2026, 1, 14, 9, 0, tzinfo=timezone.utc)
    assert cutoff.tzinfo is timezone.utc


def test_parse_ts_handles_z_suffix_as_utc():
    ts = parse_ts("2026-01-14T07:30:00Z")
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 0
    assert to_iso(ts) == "2026-01-14T07:30:00Z"


def test_selects_latest_publish_at_or_before_cutoff_only():
    delivery = date(2026, 1, 15)
    forecasts = [
        # too late — after 09:00 on D-1
        {
            "startTime": "2026-01-15T12:00:00Z",
            "publishTime": "2026-01-14T09:30:00Z",
            "generation": 9999,
        },
        # eligible but older
        {
            "startTime": "2026-01-15T12:00:00Z",
            "publishTime": "2026-01-14T04:30:00Z",
            "generation": 1000,
        },
        # latest eligible
        {
            "startTime": "2026-01-15T12:00:00Z",
            "publishTime": "2026-01-14T07:30:00Z",
            "generation": 2000,
        },
        # publish exactly at cutoff — eligible
        {
            "startTime": "2026-01-15T13:00:00Z",
            "publishTime": "2026-01-14T09:00:00Z",
            "generation": 3000,
        },
    ]
    selected = {row["startTime"]: row for row in select_decision_time_forecasts(forecasts, delivery)}
    assert selected["2026-01-15T12:00:00Z"]["forecastMw"] == 2000
    assert selected["2026-01-15T12:00:00Z"]["publishTime"] == "2026-01-14T07:30:00Z"
    assert selected["2026-01-15T13:00:00Z"]["forecastMw"] == 3000


def test_aggregate_two_half_hours_into_one_hourly_mean():
    actuals = [
        {"startTime": "2026-01-15T12:00:00Z", "fuelType": "WIND", "generation": 1000},
        {"startTime": "2026-01-15T12:30:00Z", "fuelType": "WIND", "generation": 2000},
        {"startTime": "2026-01-15T13:00:00Z", "fuelType": "WIND", "generation": 3000},
    ]
    hourly = aggregate_actuals_to_hourly(actuals)
    assert hourly["2026-01-15T12:00:00Z"] == 1500
    assert hourly["2026-01-15T13:00:00Z"] == 3000


def test_metrics_use_matched_periods_only_and_mae_bias_relationship():
    # all positive errors → MAE == bias
    m = compute_metrics([10.0, 20.0, 30.0])
    assert m["n"] == 3
    assert m["maeMw"] == 20.0
    assert m["biasMw"] == 20.0
    assert m["sameSign"] is True

    # mixed signs
    m2 = compute_metrics([10.0, -10.0])
    assert m2["maeMw"] == 10.0
    assert m2["biasMw"] == 0.0
    assert m2["sameSign"] is False


def test_missing_actual_hours_excluded_from_metrics_but_listed():
    delivery = date(2026, 1, 15)
    forecasts = [
        {
            "startTime": f"2026-01-15T{h:02d}:00:00Z",
            "publishTime": "2026-01-14T07:30:00Z",
            "generation": 1000 + h,
        }
        for h in range(24)
    ]
    # only first two half-hours of hour 0 → one hourly actual; rest missing
    actuals = [
        {
            "startTime": "2026-01-15T00:00:00Z",
            "settlementDate": "2026-01-15",
            "fuelType": "WIND",
            "generation": 900,
        },
        {
            "startTime": "2026-01-15T00:30:00Z",
            "settlementDate": "2026-01-15",
            "fuelType": "WIND",
            "generation": 1100,
        },
    ]
    series = build_day_series(forecasts, actuals, delivery)
    assert series["coverage"]["matchedHours"] == 1
    assert series["metrics"]["n"] == 1
    assert series["metrics"]["maeMw"] == 0.0  # forecast 1000 vs actual mean 1000
    assert len(series["coverage"]["missingActualHours"]) == 23
    assert series["coverage"]["missingForecastHours"] == []


def test_missing_forecast_hours_reported():
    delivery = date(2026, 1, 15)
    # only one forecast hour
    forecasts = [
        {
            "startTime": "2026-01-15T00:00:00Z",
            "publishTime": "2026-01-14T07:30:00Z",
            "generation": 5000,
        }
    ]
    actuals = [
        {
            "startTime": f"2026-01-15T{h:02d}:{m:02d}:00Z",
            "settlementDate": "2026-01-15",
            "fuelType": "WIND",
            "generation": 4000,
        }
        for h in range(24)
        for m in (0, 30)
    ]
    series = build_day_series(forecasts, actuals, delivery)
    assert series["coverage"]["forecastHours"] == 1
    assert series["coverage"]["matchedHours"] == 1
    assert len(series["coverage"]["missingForecastHours"]) == 23


def test_january_cache_coverage_and_independent_metrics():
    pytest.importorskip("json")
    from app.elexon import load_cache

    try:
        actuals, forecasts, _ = load_cache()
    except FileNotFoundError:
        pytest.skip("cache not present")

    acc = month_accuracy(forecasts, actuals, date(2026, 1, 1), date(2026, 1, 31))
    assert acc["coverage"]["matchedHours"] == 744
    assert acc["coverage"]["expectedMatchedHours"] == 744
    assert acc["coverage"]["coveragePct"] == 100.0
    assert acc["coverage"]["actualHalfHourRows"] == 1488
    assert acc["coverage"]["daysWithGaps"] == []

    # independent recompute
    errors = []
    for day_i in range(1, 32):
        series = build_day_series(forecasts, actuals, date(2026, 1, day_i))
        assert series["coverage"]["matchedHours"] == 24
        assert series["coverage"]["actualHalfHours"] == 48
        for point in series["points"]:
            if point["errorMw"] is not None:
                errors.append(point["errorMw"])
            # vintage: no later eligible publish
            cutoff = decision_cutoff_for_delivery(date(2026, 1, day_i))
            later = [
                row
                for row in forecasts
                if row["startTime"] == point["startTime"]
                and parse_ts(row["publishTime"]) <= cutoff
                and parse_ts(row["publishTime"]) > parse_ts(point["publishTime"])
            ]
            assert later == []

    n = len(errors)
    mae = sum(abs(e) for e in errors) / n
    rmse = (sum(e * e for e in errors) / n) ** 0.5
    bias = sum(errors) / n
    assert n == 744
    assert round(mae, 1) == acc["overall"]["maeMw"] == 2142.1
    assert round(rmse, 1) == acc["overall"]["rmseMw"] == 2611.7
    assert round(bias, 1) == acc["overall"]["biasMw"] == 1851.9

    # daily MAE bars use same hourly errors
    assert all(d["n"] == 24 for d in acc["daily"])
    mean_daily_mae = sum(d["maeMw"] for d in acc["daily"]) / len(acc["daily"])
    assert round(mean_daily_mae, 1) == acc["overall"]["maeMw"]
