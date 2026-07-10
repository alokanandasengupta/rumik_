import lightgbm as lgb
import pandas as pd
import joblib


class IraPreFirstMessageScorer:
    """Scores a single user using the models trained in Rumik_forecasting.ipynb.

    Kept identical to the class defined in the notebook (cell 84), only the
    import layout changed to work as a standalone module. model_dir must
    contain the six files produced by the notebook's "Save every trained
    model" cell: model_payer.txt, model_ltv.txt, model_retention_cox.pkl,
    channel_priors.csv, categorical_cols.pkl, category_levels.pkl.
    """

    def __init__(self, model_dir='.'):
        self.model_payer = lgb.Booster(model_file=f'{model_dir}/model_payer.txt')
        self.model_ltv = lgb.Booster(model_file=f'{model_dir}/model_ltv.txt')
        self.cph = joblib.load(f'{model_dir}/model_retention_cox.pkl')
        self.channel_priors = pd.read_csv(f'{model_dir}/channel_priors.csv', index_col='channel')
        self.cat_cols = joblib.load(f'{model_dir}/categorical_cols.pkl')
        self.cat_levels = joblib.load(f'{model_dir}/category_levels.pkl')
        # tuned in Step 13
        self.OPENS_CAP, self.LATENCY_CAP, self.MAX_WEIGHT = 1, 240, 0.7

    def _prep_row(self, user):
        row = pd.DataFrame([user])
        for col in self.cat_cols:
            row[col] = pd.Categorical([user.get(col, 'undefined')], categories=self.cat_levels[col])
        return row

    def _signal_weight(self, user):
        if user.get('never_activated_flag', 1) == 1:
            return 0.05
        strength = (min(user.get('n_app_opens_pre_message', 0) / self.OPENS_CAP, 1.0) * 0.5 +
                    min(user.get('browse_to_chat_latency_minutes', 0) / self.LATENCY_CAP, 1.0) * 0.5)
        return 0.20 + strength * (self.MAX_WEIGHT - 0.20)

    def score(self, user: dict):
        row = self._prep_row(user)
        model_score = self.model_payer.predict(row)[0]
        prior_score = self.channel_priors.loc[user['channel'], 'payer_rate_any_revenue']
        weight = self._signal_weight(user)
        payer_probability = weight * model_score + (1 - weight) * prior_score

        predicted_ltv = float(self.model_ltv.predict(row)[0])

        cox_row = pd.DataFrame([{c: user.get(c, 0) for c in
            ['browse_to_chat_latency_minutes', 'n_app_opens_pre_message', 'never_activated_flag',
             'channel_prior_payer_rate_any_revenue', 'is_organic', 'signup_hour_of_day']}])
        surv_fn = self.cph.predict_survival_function(cox_row, times=[1, 7, 14, 30])

        return {
            'payer_probability': round(float(payer_probability), 4),
            'signal_weight_used': round(weight, 3),
            'predicted_ltv_d30_inr': round(predicted_ltv, 2),
            'retention_probability': {
                'day_1': round(float(surv_fn.iloc[0, 0]), 4),
                'day_7': round(float(surv_fn.iloc[1, 0]), 4),
                'day_14': round(float(surv_fn.iloc[2, 0]), 4),
                'day_30': round(float(surv_fn.iloc[3, 0]), 4),
            }
        }
