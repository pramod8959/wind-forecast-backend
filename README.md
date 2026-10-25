# Wind Day-Ahead Briefing

Pilot web app for a UK energy utility’s day-ahead trading team: show the **national wind generation forecast available at decision time**, and **quantify forecast error** against outturn — scoped to **January 2026** and **Elexon wind data only**.

> **AI tools:** Built with assistance from Cursor (Composer). Domain research, Elexon API probing, decision-time join logic, React/FastAPI scaffold, Docker files, and metric validation were developed with AI pair-programming. Numbers below were recomputed from the cached extracts and spot-checked against live Elexon Insights.

---

## Product idea

GB day-ahead auctions clear power for **delivery tomorrow**. Traders need the wind forecast they can still act on **before gate** (~09:20–09:50 GMT), not a later revised forecast.

Wind forecast error quantifies renewable **uncertainty**. It does **not** by itself say how much electricity to buy — that also needs demand and other supply, which this assignment excludes.

---

## Methodology

| Topic | Choice |
|--------|--------|
| Scope | Delivery days **2026-01-01 … 2026-01-31** only |
| Decision cutoff | Latest `WINDFOR` with `publishTime ≤ 09:00 UTC` on **D−1** |
| Why 09:00? | **Configurable assumption**, set before typical EPEX (~09:20) / N2EX (~09:50) GMT gates so the vintage is available at decision time. Confirm with the client if their internal desk uses a different lock time. |
| Match key | Hourly `startTime` (UTC) |
| Forecast resolution | `WINDFOR` — **hourly** MW |
| Actual resolution | `FUELHH` `WIND` — **30-minute** MW |
| Aggregation | Each hour’s actual = mean of the two half-hours in that clock hour |
| Metrics sample | Matched hours only |
| Bias definition | `mean(forecast − actual)`; positive = over-forecast |
| Chart bars | **Daily MAE (MW)** = mean `\|forecast − actual\|` for that day’s matched hours |

### Validated January 2026 results (cache ≡ live spot-check)

| Metric | Value |
|--------|--------|
| Matched coverage | **744 / 744 (100%)** — 31 × 24 hours |
| Half-hour actual rows | **1,488** (= 31 × 48), aggregated to 744 hours — not counted as 1,488 metric periods |
| Overall MAE | **2,142.1 MW** |
| Overall RMSE | **2,611.7 MW** |
| Overall bias | **+1,851.9 MW** |
| Forecast-vintage violations | **0** (always latest eligible publish ≤ cutoff) |
| Live vs cache (2026-01-15) | Identical metrics, publish times, and all 24 hourly points |

Daily MAE bars and overall metrics use the **same** join and aggregation rules. Because every day has `n = 24`, the mean of daily MAEs equals the overall MAE.

---

## Architecture

```text
Elexon Insights (FUELHH + WINDFOR)
        │
        ▼
  scripts/etl.py  →  backend/data/*.json  (committed Jan 2026 cache)
        │
        ▼
  FastAPI (analysis.py: cutoff select → join → MAE/RMSE/bias)
        │
        ▼
  React UI  — Day-ahead briefing | Forecast accuracy
```

- **Backend:** Python FastAPI; serves from cache (demo-stable, no live rate-limit risk).
- **Frontend:** React + Vite + Recharts; Vite proxies `/api` in dev; nginx proxies `/api` in Docker.
- **Containers:** `docker-compose.yml` builds both services.

---

## Repository layout

```text
.
├── README.md
├── docker-compose.yml
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py          # FastAPI routes
│   │   ├── analysis.py      # decision-time join + metrics
│   │   ├── elexon.py        # Elexon client + cache loader
│   │   └── config.py        # cutoff + date scope
│   ├── scripts/etl.py       # refresh FUELHH + WINDFOR cache
│   └── data/                # Jan 2026 extracts (committed)
└── frontend/
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── vite.config.js
    └── src/                 # App, BriefingView, AccuracyView
```

---

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness + cache sizes |
| GET | `/api/meta` | Scope + decision-cutoff rule |
| GET | `/api/briefing/{YYYY-MM-DD}` | Decision-time forecast vs actual for one delivery day |
| GET | `/api/accuracy?from=&to=` | Month MAE / RMSE / bias + daily breakdown + coverage |

Data sources (public, no API key):

- Actuals: `https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH/stream?fuelType=WIND`
- Forecasts: `https://data.elexon.co.uk/bmrs/api/v1/datasets/WINDFOR/stream`

---

## Run with Docker

```bash
docker compose up --build
```

- UI: http://localhost:3000  
- API docs: http://localhost:8000/docs  

---

## Run locally (dev)

**Backend** (Python 3.12 recommended):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# optional: python scripts/etl.py   # refresh cache from Elexon
uvicorn app.main:app --reload --port 8000
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

UI: http://localhost:5173 (proxies `/api` → `:8000`).

---

## Deployed app

- **Live URL:** _add after deploy (Vercel frontend + Render/Railway/Heroku API, or single Heroku Docker stack)_  
- **Video demo (unlisted YouTube):** _add after recording_  

Suggested split: frontend on **Vercel** (`VITE_API_BASE` → public API URL); backend on **Render/Railway/Heroku** from `backend/Dockerfile` with `backend/data` included in the image.

---

## Limitations

- National **wind only** (no demand, other fuels, prices, or portfolio positions).
- **09:00 UTC** cutoff is a documented desk assumption, not a confirmed client SOP.
- Accuracy dashboard uses the **cached** January extract (refresh via `etl.py`).
- Does not recommend a MW buy quantity — only forecast uncertainty for renewables.

---

## Tests

```bash
cd backend
source .venv/bin/activate   # or: python3.12 -m venv .venv && pip install -r requirements.txt
pytest -q
python scripts/verify_checklist.py   # live Elexon shape check + cache recompute
```

Covers: D−1 09:00 UTC cutoff, Zulu timezone parsing, latest-eligible vintage, half-hour→hour aggregation, missing-period handling, and independent MAE/RMSE/bias vs January cache.

## Notes for reviewers

1. Open **Forecast accuracy** → confirm coverage **744/744 (100%)** and chart title **Daily MAE (MW)**.  
2. Click a day → briefing shows **decision date**, full cutoff timestamp, forecast vintage, matched-hour coverage %, and any missing hours.  
3. Optional: `python scripts/etl.py` then re-hit `/api/accuracy` to refresh from live Elexon.

## Submission checklist status

### Application and data
- [x] Verify Elexon FUELHH / WINDFOR endpoint responses  
- [x] Verify forecast-vintage selection (`publishTime` ≤ D−1 cutoff)  
- [x] Confirm 744 hours from matched half-hourly records (1,488 → 744)  
- [x] Matched-period coverage + missing-data handling on day briefing  
- [x] MAE / RMSE / bias / daily MAE verified independently  

### Engineering
- [ ] Docker Compose startup (Docker not installed on this build machine — run `docker compose up --build` locally)  
- [x] Automated tests for cutoff, timezones, missing periods, metrics  
- [x] README: architecture, API, assumptions, setup, limitations  
- [x] AI tools disclosed in README  

### Submission (manual)
- [ ] Deploy frontend + backend; test public URL  
- [ ] Customer pitch video ≤ 5 min  
- [ ] Technical walkthrough ≤ 5 min  
- [ ] Unlisted YouTube URL in submission form
