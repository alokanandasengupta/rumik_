# Backend

FastAPI service wrapping the `IraPreFirstMessageScorer` class trained in
`Rumik_forecasting.ipynb`.

## Getting the trained models

The service loads six files from `MODEL_DIR` (default `backend/models/`):
`model_payer.txt`, `model_ltv.txt`, `model_retention_cox.pkl`,
`channel_priors.csv`, `categorical_cols.pkl`, `category_levels.pkl`.

Two ways to produce them:

**Option A: run `train_model.py` (no Colab needed)**

```bash
cd backend
pip install -r requirements.txt
DATA_FILE=/path/to/IRA_Rumik_Synthetic_Product_Analytics_6mo_50K.xlsx python train_model.py
```

This is a standalone, linear version of the notebook's Sections 1-8, reading
the same source Excel file and writing the same six files straight into
`MODEL_DIR`. By default it looks for the data file at
`../data/IRA_Rumik_Synthetic_Product_Analytics_6mo_50K.xlsx` (repo-root
`data/`), override with `DATA_FILE` if yours lives elsewhere. It also
reconstructs two things missing from the saved notebook itself (not
something this script introduces): the `numeric_cols_v2` /
`categorical_cols_v2` / `boolean_cols_v2` definitions used from cell 58
onward were never saved to the `.ipynb`, a defining cell got lost somewhere
in Colab, see the comment above that block in `train_model.py` for exactly
what was reconstructed and from where.

**Option B: run the notebook in Colab**

Open `Rumik_forecasting.ipynb` with your Drive mounted, run through Section
8's "Save every trained model" cell, then download the six resulting files
from Colab's file panel (they land in `/content/`) into `backend/models/`.

Either way, `GET /api/health` reports which of the six files, if any, are
still missing, the server won't crash without them, it just returns 503 on
`/api/score` until they're all in place.

## Running

Plain local run:

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8001
```

Under supervisord (this environment's process manager), see
`../supervisord.conf` at the repo root, it runs this same command on port
8001 alongside the frontend, `PORT` is overridable via `backend/.env` (copy
from `.env.example`).

## Endpoints

Everything is under `/api`, this environment's ingress is expected to route
that path prefix to this service and everything else to the frontend.

- `GET /api/health` — model load status.
- `GET /api/options` — valid values for every categorical field plus the
  list of known channels, read straight from the trained model's category
  levels, so the frontend never has to guess or hardcode them.
- `POST /api/score` — takes one user's signup-time details plus
  (optionally) their pre-message behavior, returns `payer_probability`,
  `signal_weight_used`, `predicted_ltv_d30_inr`, and `retention_probability`
  for days 1, 7, 14, and 30, the same shape as the notebook's last cell.

`channel_prior_*` and `is_organic` are not sent by the client, they're looked
up and derived server-side from the chosen channel, since those are facts
about the channel, not something a caller should have to know.
