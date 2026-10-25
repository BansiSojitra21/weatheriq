# WeatherIQ

WeatherIQ is a local weather-intelligence dashboard. It stores Open-Meteo observations and forecasts, trains short-horizon models on historical daily data, flags unusual measurements, and evaluates configurable risk rules.

It is an analytical tool. It is not a replacement for official emergency alerts or professional meteorological forecasts. Open-Meteo fields are model and reanalysis output, not readings from a local weather station. Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## What is running

| Surface | URL |
| --- | --- |
| Next.js dashboard | http://127.0.0.1:3000 |
| FastAPI | http://127.0.0.1:8000/api/v1 |
| OpenAPI | http://127.0.0.1:8000/docs |
| PostgreSQL in Compose | localhost:5432 |

The browser talks to `/api/proxy`, which adds `X-API-Key` only for non-GET requests. The key is not exposed as a `NEXT_PUBLIC` variable.

## Verified on this machine

Checked on 21 October 2026. Docker and PostgreSQL are not installed here, so the working database is SQLite at `data/weatheriq.db`. Compose is written for PostgreSQL and was not started.

| Check | Result |
| --- | --- |
| `pytest` | 16 passed, 1 Starlette deprecation warning |
| `ruff check services scripts ml` | passed |
| `npm test` (Vitest) | 6 passed |
| `npx eslint src --max-warnings 0` | passed |
| `npx tsc --noEmit` | passed |
| Current web validation | lint, type-check, 5 unit tests, and production build passed |
| API tests | 28 passed |
| Playwright | not run after the Weather Intelligence updates; Chromium availability not verified |
| Open-Meteo bootstrap | 4 cities, exit 0 |
| Alembic `e99438373e02` | generated and upgraded on a temporary SQLite database |
| Docker Compose | not run |

Browser checks on the running app: Mumbai loaded at 32.5°C, clear sky, with an external hourly chart and seven-day forecast. Analytics switched to precipitation and showed the correlation table. The forecast page showed a LightGBM prediction beside a separately labeled Open-Meteo high/low. Anomalies listed exploratory robust-z events and stated they are not hazard warnings. A workflow event appeared as **Not delivered**, then Acknowledge changed it to acknowledged without marking it delivered. Imperial units converted the same observation to 90.5°F. Light theme and the phone-width navigation menu both worked.

## Model results

Trained by `scripts/bootstrap.py` on 21 October 2026. Versions: temperature `ti-20261021T121434Z`, precipitation `pr-20261021T121437Z`, anomaly `an-20261021T121439Z`. Algorithm for the supervised models is LightGBM. Seed 42. Chronological split by issuance date, about 70/15/15. Validation was not used to fit the temperature model. The precipitation decision threshold was chosen by maximum F1 on validation and then frozen. Metrics below are holdout scores, not training scores.

Daily observations used for training run from 2024-10-21 through 2026-10-20: 2,920 daily rows and 2,016 hourly rows across Mumbai, Delhi, London, and New York. Horizon-1 temperature split: train 2024-11-03 to 2026-03-18 (2,004 rows), validation 2026-03-19 to 2026-07-03 (428), test 2026-07-04 to 2026-10-19 (432).

Temperature holdout, daily mean °C:

| Horizon | ML MAE | ML RMSE | Persistence MAE | Fourier MAE | Skill vs persistence | Skill vs Fourier | 10–90% coverage | Test rows |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 day | 1.134 | 1.529 | 1.202 | 1.127 | 0.057 | -0.006 | 0.576 | 432 |
| 2 days | 1.564 | 2.080 | 1.741 | 1.520 | 0.102 | -0.029 | 0.597 | 432 |
| 3 days | 1.753 | 2.340 | 1.953 | 1.642 | 0.102 | -0.067 | 0.553 | 432 |
| 7 days | 1.826 | 2.438 | 2.196 | 1.769 | 0.168 | -0.032 | 0.600 | 428 |

The tree model beats persistence by a small amount. It does not beat the per-location Fourier baseline on this holdout. The quantile band is the model's 10th to 90th percentile. Holdout coverage is about 55–60%, so it is not a calibrated 80% interval. A rolling-origin check for the 1-day horizon finished with mean MAE 1.409 and was not used to tune the model.

Open-Meteo previous-run forecasts, aggregated from hourly values to a daily mean and scored only on dates that API returned (368 pairs, separate from the ML holdout): lead 1 MAE 0.619°C, lead 2 0.753°C, lead 3 0.792°C, lead 7 1.273°C. That numerical forecast is a different product and a stronger temperature benchmark on its own sample. It is not an ML feature.

Precipitation occurrence is a day above 0.1 mm. The frozen decision threshold is 0.1, which favors recall.

| Horizon | F1 | PR-AUC | Brier | Persistence F1 | Amount MAE, all days (mm) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 day | 0.835 | 0.921 | 0.163 | 0.820 | 5.416 |
| 2 days | 0.808 | 0.896 | 0.204 | 0.791 | 6.420 |
| 3 days | 0.807 | 0.886 | 0.202 | 0.786 | 7.079 |

Anomaly detection is exploratory. There are no labeled anomalies, so no precision or recall is reported. The database currently holds 33 anomaly events from robust z-scores and Isolation Forest. A flagged value is an unusual measurement relative to recent history, not a danger warning. The anomaly model record does not store a training start date; the monitoring page shows that start as unavailable.

Retraining is manual. Nothing in this project retrains models on a schedule.

## Local setup without Docker

Requirements: Python 3.13, Node.js 24, and npm. PostgreSQL is optional.

```powershell
cd weatheriq
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.venv\Scripts\python.exe scripts\bootstrap.py
```

Bootstrap ingests Open-Meteo history, current conditions, the live forecast, and previous-run benchmarks for the four seed cities, then trains and evaluates the models. Use `--skip-ingest` or `--skip-train` to repeat only one side. `scripts/refresh_weather.py` refreshes current conditions and forecasts and evaluates rules. It does not retrain.

Enabled alert rules are evaluated once when created or re-enabled, then automatically every five minutes while the API is running. Scheduled checks refresh stale city weather snapshots before evaluating. The Weather Intelligence page polls for new alerts every 30 seconds and can show native Chrome notifications after permission is granted; enabling them sends a test notification. Keep the page open, including in a background tab, to receive notifications. This local setup does not send background push after the page is closed, SMS, or email notifications. Set `WEATHERIQ_ALERT_SCHEDULE_ENABLED=false` to disable scheduled checks.

API:

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir services/api --host 127.0.0.1 --port 8000
```

Web:

```powershell
cd apps\web
Copy-Item ..\..\.env.example .env.local
# Set API_INTERNAL_BASE_URL=http://127.0.0.1:8000/api/v1
# Set WEATHERIQ_API_KEY to the same value as the API
npm install --legacy-peer-deps
npm run dev
```

`--legacy-peer-deps` is required. `@hookform/resolvers` 6 declares optional Effect peers that npm cannot resolve together.

SQLite tables are created on startup. For PostgreSQL, set `WEATHERIQ_DATABASE_URL`, set `WEATHERIQ_AUTO_CREATE_SCHEMA=false`, and run:

```powershell
cd services\api
..\.venv\Scripts\python.exe -m alembic upgrade head
```

Useful commands:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check services scripts ml
cd apps\web
npm test
npx eslint src --max-warnings 0
npx playwright test
```

Playwright expects the API on port 8000 and reuses a Next.js server already on port 3000.

## Docker Compose

`infra/docker-compose.yml` defines PostgreSQL 16, the API, and the web app. This machine has no Docker, so that file has not been executed.

```powershell
docker compose -f infra/docker-compose.yml up --build
```

The API container runs `alembic upgrade head` before Uvicorn. Model artifacts and the Open-Meteo cache use named volumes.

## Data and API behavior

Observations, issued forecasts, ML predictions, anomaly events, and rule alerts are stored separately. Live forecast issuance time is the retrieval time, because the free Open-Meteo response used here has no model-run timestamp. Previous-run lead times are stored on their own forecast slots.

Mutating routes require `X-API-Key`. The development default is `dev-weatheriq-key`. Change it before exposing the API.

Open-Meteo's free API is for non-commercial use, with published limits of 10,000 calls per day, 5,000 per hour, and 600 per minute. Commercial or high-volume hosting needs Open-Meteo's paid plan. This project does not invent observations when a request fails.

## Layout

- `apps/web` — Next.js 16 App Router, React 19, TypeScript, Tailwind 4
- `services/api` — FastAPI, SQLAlchemy 2, Alembic
- `ml` — features, chronological splits, training, anomaly scoring
- `scripts` — bootstrap, training, refresh
- `infra` — Compose and Dockerfiles
