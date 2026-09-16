# Rumik Payer Scoring Tool

A FastAPI + vanilla-JS app that turns a trained churn/payer-prediction model
into something a growth or product team can actually use: enter a user's
signup details, get back payer probability, predicted 30-day spend, and a
day 1/7/14/30 retention curve. Includes a self-contained analytics dashboard
built on a 15K-user synthetic dataset for exploring the underlying model
without needing live data.

**Stack**: FastAPI (Python) backend, static HTML/JS frontend (no build
step), Chart.js for visualization. Models (LightGBM for payer
probability/spend, `lifelines` for the retention survival curve) trained
from a Jupyter notebook.

## App

`backend/` and `frontend/` turn the scoring tool from
`Rumik_forecasting.ipynb` (Section 8, `IraPreFirstMessageScorer`) into a form
you can actually use: fill in a user's signup details (and, once known,
their pre-message behavior), get back payer probability, predicted 30-day
spend, and a day 1/7/14/30 retention curve.

- `backend/` — FastAPI service on port 8001, everything under `/api`, see
  `backend/README.md` for how to get the trained model files in place
  (either run `backend/train_model.py` against the source data file, or
  export them from the notebook in Colab) and run it.
- `frontend/index.html` — the scorer form, no build step, on port 3000.
  Calls the backend at `REACT_APP_BACKEND_URL` (set in `frontend/.env`,
  copy from `.env.example`) if set, otherwise same-origin `/api`.
- `frontend/dashboard.html` — a self-contained analytics dashboard (15K
  synthetic users, Chart.js, embedded dataset) covering revenue, acquisition,
  engagement, retention, support, and payer economics, a "Concept" tab
  explaining the models in plain language, plus a "Try it live" widget that
  calls the same backend `/api/score` as the scorer form. The pages
  cross-link to each other. Once real models are loaded, the widget's
  dropdowns update automatically since they're read from `/api/options`,
  nothing here is hardcoded to the placeholder schema.
- `data/` — the source Excel file
  (`IRA_Rumik_Synthetic_Product_Analytics_6mo_15K_subsample.xlsx`) used by
  `train_model.py` to produce the models is committed here.
- `supervisord.conf` — runs backend and frontend together as this
  environment expects (`pip install supervisor`, then `supervisord -c
  supervisord.conf` from the repo root).

## Running locally without supervisord

```bash
# terminal 1
cd backend && pip install -r requirements.txt && uvicorn app:app --reload --port 8001

# terminal 2
cd frontend && REACT_APP_BACKEND_URL=http://localhost:8001 ./start.sh
```

Open `http://localhost:3000`.
