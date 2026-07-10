# rumik_
rumik_

## App

`backend/` and `frontend/` turn the scoring tool from
`Rumik_forecasting.ipynb` (Section 8, `IraPreFirstMessageScorer`) into a form
you can actually use: fill in a user's signup details (and, once known,
their pre-message behavior), get back payer probability, predicted 30-day
spend, and a day 1/7/14/30 retention curve.

- `backend/` — FastAPI service, see `backend/README.md` for how to get the
  trained model files in place and run it.
- `frontend/` — a static HTML page, no build step. Open `frontend/index.html`
  directly in a browser, or serve it (`python -m http.server` from inside
  `frontend/`), with the backend running at `http://localhost:8000`.
