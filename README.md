# Wind Day-Ahead Briefing — Backend

FastAPI service for UK day-ahead wind forecast briefing and January 2026 accuracy metrics (Elexon `FUELHH` + `WINDFOR`).

Frontend repo: https://github.com/pramod8959/wind-forecast-frontend

> **AI tools:** Built with assistance from Cursor (Composer).

## Run locally

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

```bash
pytest -q
python scripts/verify_checklist.py
```

## Docker

```bash
docker compose up --build
```

## Decision rule

For delivery day **D**, use the latest `WINDFOR` with `publishTime ≤ 09:00 UTC` on **D−1**. Join on hourly `startTime`; actuals are means of two `FUELHH` half-hours. Metrics use matched hours only (Jan 2026: **744/744**).

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/meta` | Scope + cutoff |
| GET | `/api/briefing/{YYYY-MM-DD}` | Day briefing |
| GET | `/api/accuracy` | January MAE / RMSE / bias |

## Limitations

Wind only; 09:00 UTC cutoff is a documented assumption; does not compute buy volume (no demand/other supply).
