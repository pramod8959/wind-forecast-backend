from pathlib import Path

# Day-ahead decision cutoff on D-1 (UTC). Conservative vs EPEX ~09:20 / N2EX ~09:50 GMT.
DECISION_CUTOFF_HOUR_UTC = 9
DECISION_CUTOFF_MINUTE_UTC = 0

# Scope: purchase decisions for January 2026 delivery days
DELIVERY_MONTH_START = "2026-01-01"
DELIVERY_MONTH_END = "2026-01-31"

# Forecasts needed from late Dec (for Jan 1 decisions) through Jan 30 publishes
FORECAST_PUBLISH_FROM = "2025-12-30T00:00:00Z"
FORECAST_PUBLISH_TO = "2026-01-31T12:00:00Z"

ELEXON_BASE = "https://data.elexon.co.uk/bmrs/api/v1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ACTUALS_PATH = DATA_DIR / "actuals_wind_jan2026.json"
FORECASTS_PATH = DATA_DIR / "forecasts_windfor.json"
META_PATH = DATA_DIR / "meta.json"