# Backend

FastAPI service wrapping the `IraPreFirstMessageScorer` class trained in
`Rumik_forecasting.ipynb`.

## Getting the trained models

This service does not train anything itself, it loads the six files the
notebook saves in its "Save every trained model" cell (Step 14). To produce
them:

1. Open `Rumik_forecasting.ipynb` in Colab with your Drive mounted.
2. Run through Section 8 (Step 14), specifically the cell that calls:
   ```python
   model_lgb.save_model('model_payer.txt')
   model_ltv.save_model('model_ltv.txt')
   joblib.dump(cph, 'model_retention_cox.pkl')
   channel_priors.to_csv('channel_priors.csv')
   joblib.dump(list(X_train_lgb.dtypes[X_train_lgb.dtypes == 'category'].index), 'categorical_cols.pkl')
   joblib.dump({col: X_train_lgb[col].cat.categories.tolist() for col in full_cat_cols}, 'category_levels.pkl')
   ```
3. Download the six resulting files from Colab's file panel (they land in
   `/content/`), and drop them into this folder, `backend/models/`, keeping
   the same filenames:
   - `model_payer.txt`
   - `model_ltv.txt`
   - `model_retention_cox.pkl`
   - `channel_priors.csv`
   - `categorical_cols.pkl`
   - `category_levels.pkl`

The server checks for these on startup. `GET /health` reports which ones, if
any, are still missing, it won't crash without them, it just returns 503 on
`/score` until they're all in place.

## Running

```bash
cd backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

## Endpoints

- `GET /health` — model load status.
- `GET /options` — valid values for every categorical field plus the list of
  known channels, read straight from the trained model's category levels, so
  the frontend never has to guess or hardcode them.
- `POST /score` — takes one user's signup-time details plus (optionally)
  their pre-message behavior, returns `payer_probability`,
  `signal_weight_used`, `predicted_ltv_d30_inr`, and `retention_probability`
  for days 1, 7, 14, and 30, the same shape as the notebook's last cell.

`channel_prior_*` and `is_organic` are not sent by the client, they're looked
up and derived server-side from the chosen channel, since those are facts
about the channel, not something a caller should have to know.
