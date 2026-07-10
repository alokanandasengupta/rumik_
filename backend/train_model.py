"""Standalone, non-Colab version of Rumik_forecasting.ipynb Sections 1-8.

Reads the same source Excel file the notebook does and produces the same
six model artifacts the notebook's "Save every trained model" cell does,
so this environment can train real models without Google Drive or Colab.

Reconstructs two things the saved notebook is missing (both are real gaps
in the .ipynb file itself, not something introduced here):

1. numeric_cols_v2 / categorical_cols_v2 / boolean_cols_v2 are used
   starting at the notebook's cell 58 but never assigned anywhere in the
   file, a defining cell was lost somewhere in Colab. Reconstructed here
   exactly as pasted earlier from that missing cell's own content.
2. cell 86/87's brand_new_user / engaged_user dicts, used only for the
   notebook's own manual smoke test, are not needed by this script at all,
   the API's ScoreRequest model replaces them.

Run:
    DATA_FILE=/path/to/IRA_Rumik_Synthetic_Product_Analytics_6mo_50K.xlsx \
    MODEL_DIR=./models \
    python train_model.py
"""
import os

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from lifelines import CoxPHFitter
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

HERE = os.path.dirname(__file__)
DATA_FILE = os.environ.get(
    'DATA_FILE',
    os.path.join(HERE, '..', 'data', 'IRA_Rumik_Synthetic_Product_Analytics_6mo_50K.xlsx'),
)
MODEL_DIR = os.environ.get('MODEL_DIR', os.path.join(HERE, 'models'))
os.makedirs(MODEL_DIR, exist_ok=True)


def log(msg):
    print(f'[train_model] {msg}')


# --- Load (cells 3, 5) ---------------------------------------------------
log(f'Loading {DATA_FILE}')
xl = pd.ExcelFile(DATA_FILE)
dim_users = pd.read_excel(DATA_FILE, sheet_name='dim_users')
fact_events = pd.read_excel(DATA_FILE, sheet_name='fact_events')
subscription_lifecycle = pd.read_excel(DATA_FILE, sheet_name='subscription_lifecycle')
log(f'dim_users {dim_users.shape}, fact_events {fact_events.shape}, '
    f'subscription_lifecycle {subscription_lifecycle.shape}')

# --- Draw the pre-first-message line (cell 13) ---------------------------
non_signup = fact_events[fact_events.event_name != 'User Signed Up']
first_interaction = non_signup.groupby('user_id')['event_ts'].min().rename('first_interaction_ts')

msg_events = fact_events[fact_events.event_name.isin(['Message Sent', 'Message Received'])]
first_message = msg_events.groupby('user_id')['event_ts'].min().rename('first_message_ts')

bridge_first_interaction = (
    dim_users[['user_id', 'signup_ts']]
    .merge(first_message, on='user_id', how='left')
    .merge(first_interaction, on='user_id', how='left')
)
bridge_first_interaction['activation_flag'] = bridge_first_interaction['first_message_ts'].notna()
bridge_first_interaction['has_any_interaction_flag'] = bridge_first_interaction['first_interaction_ts'].notna()
bridge_first_interaction['browse_to_chat_latency_minutes'] = (
    (bridge_first_interaction['first_message_ts'] - bridge_first_interaction['first_interaction_ts'])
    .dt.total_seconds() / 60
)

# --- Labels: maturity, LTV, retention (cells 19, 21, 23, 26) --------------
EVENT_END = pd.Timestamp('2026-07-09 23:59:59')
label_table = dim_users[['user_id', 'signup_ts']].copy()
label_table['days_observed'] = ((EVENT_END - label_table['signup_ts']).dt.total_seconds() / 86400).clip(upper=30)
label_table['label_mature_d30'] = label_table['days_observed'] >= 30

d30_cutoff = label_table.set_index('user_id')['signup_ts'] + pd.Timedelta(days=30)

sub_rev = subscription_lifecycle[subscription_lifecycle.event_name.isin(['Subscription Purchased', 'Subscription Renewed'])].copy()
sub_rev['cutoff'] = sub_rev['user_id'].map(d30_cutoff)
sub_rev_d30 = sub_rev[sub_rev.event_ts <= sub_rev.cutoff]

pack_rev = fact_events[fact_events.event_name == 'Credit Pack Purchase Completed'].copy()
pack_rev['cutoff'] = pack_rev['user_id'].map(d30_cutoff)
pack_rev_d30 = pack_rev[pack_rev.event_ts <= pack_rev.cutoff]

sub_ltv = sub_rev_d30.groupby('user_id')['amount_inr'].sum().rename('sub_ltv_d30')
pack_ltv = pack_rev_d30.groupby('user_id')['amount_inr'].sum().rename('pack_ltv_d30')

label_table = label_table.merge(sub_ltv, on='user_id', how='left').merge(pack_ltv, on='user_id', how='left')
label_table[['sub_ltv_d30', 'pack_ltv_d30']] = label_table[['sub_ltv_d30', 'pack_ltv_d30']].fillna(0)
label_table['ltv_d30'] = label_table['sub_ltv_d30'] + label_table['pack_ltv_d30']

last_activity = fact_events[fact_events.event_name != 'User Signed Up'].groupby('user_id')['event_ts'].max().rename('last_event_ts')
label_table = label_table.merge(last_activity, on='user_id', how='left')
signup_map = dim_users.set_index('user_id')['signup_ts']
label_table['last_active_offset_days'] = (
    (label_table['last_event_ts'] - label_table['user_id'].map(signup_map)).dt.total_seconds() / 86400
).clip(lower=0)
label_table['still_active_at_censor'] = (
    label_table['days_observed'] - label_table['last_active_offset_days']
) <= 2

label_table['is_payer_d30_subscription_only'] = label_table['sub_ltv_d30'] > 0
label_table['is_payer_d30_any_revenue'] = label_table['ltv_d30'] > 0
log(f'label_table {label_table.shape}, payer rate (any revenue) '
    f'{label_table.is_payer_d30_any_revenue.mean():.4f}')

# --- T0 features + channel priors (cells 28, 30, 32) ----------------------
t0_features = dim_users[[
    'user_id', 'platform', 'country_code', 'pricing_region_at_signup',
    'creation_source', 'active_experiment', 'media_source', 'campaign', 'channel',
    'ad_set_id', 'ad_id', 'device_model', 'os_version',
    'ad_intent', 'targeting_age_bucket', 'targeting_gender', 'targeting_interest',
    'nudge_experiment_arm',
]].copy()
t0_features['signup_hour_of_day'] = dim_users['signup_ts'].dt.hour
t0_features['signup_day_of_week'] = dim_users['signup_ts'].dt.dayofweek
t0_features['is_organic'] = t0_features['media_source'].isin(['undefined']) | t0_features['channel'].isin(['Organic App Store', 'User Invite'])

TRAIN_CUTOFF = pd.Timestamp('2026-05-01')
prior_population = dim_users.merge(label_table.drop(columns=['signup_ts']), on='user_id')
prior_population = prior_population[
    (prior_population.signup_ts < TRAIN_CUTOFF) & (prior_population.label_mature_d30)
]
channel_priors = prior_population.groupby('channel').agg(
    n_users=('user_id', 'count'),
    payer_rate_subscription=('is_payer_d30_subscription_only', 'mean'),
    payer_rate_any_revenue=('is_payer_d30_any_revenue', 'mean'),
    avg_ltv_d30=('ltv_d30', 'mean'),
).round(4)

t0_features = t0_features.merge(
    channel_priors[['payer_rate_subscription', 'payer_rate_any_revenue', 'avg_ltv_d30']]
    .rename(columns=lambda c: f'channel_prior_{c}'),
    on='channel', how='left',
)

# --- Master table, trainable rows, time-quantile split (cells 35, 39, 42) -
master_table = t0_features.merge(label_table, on='user_id', how='inner')
trainable = master_table[master_table.label_mature_d30].copy()

train_cutoff, val_cutoff = trainable['signup_ts'].quantile([0.70, 0.85])
train = trainable[trainable.signup_ts <= train_cutoff]
val = trainable[(trainable.signup_ts > train_cutoff) & (trainable.signup_ts <= val_cutoff)]
log(f'train {len(train)} rows, val {len(val)} rows')

# --- Baseline logistic regression, T0-only (cells 44, 46, 51) -------------
categorical_cols = ['platform', 'country_code', 'pricing_region_at_signup', 'creation_source',
                    'active_experiment', 'channel', 'ad_intent', 'targeting_age_bucket',
                    'targeting_gender', 'targeting_interest', 'nudge_experiment_arm']
numeric_cols = ['signup_hour_of_day', 'signup_day_of_week', 'is_organic',
                'channel_prior_payer_rate_subscription', 'channel_prior_payer_rate_any_revenue',
                'channel_prior_avg_ltv_d30']
TARGET = 'is_payer_d30_any_revenue'
categorical_cols_fixed = [c for c in categorical_cols if c != 'country_code']

preprocessor_fixed = ColumnTransformer([
    ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_cols_fixed),
    ('num', StandardScaler(), numeric_cols),
])
logreg_pipeline_fixed = Pipeline([
    ('preprocess', preprocessor_fixed),
    ('model', LogisticRegression(max_iter=1000, class_weight='balanced')),
])
logreg_pipeline_fixed.fit(train[categorical_cols_fixed + numeric_cols], train[TARGET])
val_probs_fixed = logreg_pipeline_fixed.predict_proba(val[categorical_cols_fixed + numeric_cols])[:, 1]
log(f'T0-only baseline ROC-AUC {roc_auc_score(val[TARGET], val_probs_fixed):.4f}, '
    f'PR-AUC {average_precision_score(val[TARGET], val_probs_fixed):.4f}')

# --- Pre-message (T0+) features (cells 54, 56, 57) ------------------------
pre_message_events = fact_events.merge(
    bridge_first_interaction[['user_id', 'first_message_ts']], on='user_id', how='inner',
)
pre_message_events = pre_message_events[pre_message_events.event_ts < pre_message_events.first_message_ts]
pre_message_events = pre_message_events[pre_message_events.event_name != 'User Signed Up']

t0plus_agg = pre_message_events.groupby('user_id').agg(
    n_app_opens_pre_message=('event_name', lambda s: (s == 'App Opened').sum()),
    saw_plans_pre_message=('event_name', lambda s: (s == 'Subscription Plans Viewed').any()),
    purchased_pre_message=('event_name', lambda s: s.isin(
        ['Subscription Purchase Completed', 'Subscription Purchased', 'purchase']).any()),
    pre_message_revenue=('amount_inr', 'sum'),
).reset_index()

t0plus_features = t0_features.merge(
    bridge_first_interaction[['user_id', 'browse_to_chat_latency_minutes']], on='user_id', how='left',
).merge(t0plus_agg, on='user_id', how='left')

fill_cols = ['n_app_opens_pre_message', 'saw_plans_pre_message', 'purchased_pre_message', 'pre_message_revenue']
t0plus_features[fill_cols] = t0plus_features[fill_cols].fillna({
    'n_app_opens_pre_message': 0, 'saw_plans_pre_message': False,
    'purchased_pre_message': False, 'pre_message_revenue': 0,
})

# --- Reconstructed: the notebook cell that defines these was lost --------
# (verbatim from what was pasted earlier when walking through Section 5)
numeric_cols_v2 = numeric_cols + ['browse_to_chat_latency_minutes', 'n_app_opens_pre_message', 'pre_message_revenue']
categorical_cols_v2 = categorical_cols_fixed
boolean_cols_v2 = ['saw_plans_pre_message', 'purchased_pre_message']

# --- T0+ splits, never_activated_flag (cell 58, 59) -----------------------
master_table_v2 = t0plus_features.merge(label_table, on='user_id', how='inner')
trainable_v2 = master_table_v2[master_table_v2.label_mature_d30].copy()
train_v2 = trainable_v2[trainable_v2.signup_ts <= train_cutoff].copy()
val_v2 = trainable_v2[(trainable_v2.signup_ts > train_cutoff) & (trainable_v2.signup_ts <= val_cutoff)].copy()

for df in [train_v2, val_v2]:
    df['never_activated_flag'] = df['browse_to_chat_latency_minutes'].isna().astype(int)
    df['browse_to_chat_latency_minutes'] = df['browse_to_chat_latency_minutes'].fillna(0)

numeric_cols_v2_fixed = numeric_cols_v2 + ['never_activated_flag']
log(f'train_v2 {len(train_v2)} rows, val_v2 {len(val_v2)} rows')

# --- LightGBM payer model (cells 65, 67) ----------------------------------
full_cat_cols = categorical_cols_v2
full_num_cols = numeric_cols_v2_fixed + boolean_cols_v2

X_train_lgb = train_v2[full_cat_cols + full_num_cols].copy()
X_val_lgb = val_v2[full_cat_cols + full_num_cols].copy()
for col in full_cat_cols:
    X_train_lgb[col] = X_train_lgb[col].astype('category')
    X_val_lgb[col] = X_val_lgb[col].astype('category').cat.set_categories(X_train_lgb[col].cat.categories)

y_train_lgb = train_v2[TARGET]
y_val_lgb = val_v2[TARGET]

lgb_train = lgb.Dataset(X_train_lgb, label=y_train_lgb, categorical_feature=full_cat_cols)
lgb_val = lgb.Dataset(X_val_lgb, label=y_val_lgb, categorical_feature=full_cat_cols, reference=lgb_train)
params = {
    'objective': 'binary',
    'metric': 'average_precision',
    'is_unbalance': True,
    'learning_rate': 0.05,
    'num_leaves': 15,
    'verbose': -1,
}
model_lgb = lgb.train(
    params, lgb_train, num_boost_round=500,
    valid_sets=[lgb_val], valid_names=['val'],
    callbacks=[lgb.early_stopping(stopping_rounds=30), lgb.log_evaluation(0)],
)
val_probs_lgb = model_lgb.predict(X_val_lgb)
log(f'LightGBM payer model ROC-AUC {roc_auc_score(y_val_lgb, val_probs_lgb):.4f}, '
    f'PR-AUC {average_precision_score(y_val_lgb, val_probs_lgb):.4f}, '
    f'best_iteration {model_lgb.best_iteration}')

# --- Survival data (cell 71) ----------------------------------------------
survival_data = label_table.merge(t0plus_features[['user_id']], on='user_id')
survival_data['duration'] = survival_data['last_active_offset_days'].fillna(0)
survival_data['event_observed'] = (~survival_data['still_active_at_censor']).astype(int)

# --- LTV model (cell 76) --------------------------------------------------
lgb_train_ltv = lgb.Dataset(X_train_lgb, label=train_v2['ltv_d30'], categorical_feature=full_cat_cols)
lgb_val_ltv = lgb.Dataset(X_val_lgb, label=val_v2['ltv_d30'], categorical_feature=full_cat_cols, reference=lgb_train_ltv)
params_ltv = {
    'objective': 'tweedie',
    'tweedie_variance_power': 1.5,
    'metric': 'rmse',
    'learning_rate': 0.05,
    'num_leaves': 15,
    'verbose': -1,
}
model_ltv = lgb.train(
    params_ltv, lgb_train_ltv, num_boost_round=500,
    valid_sets=[lgb_val_ltv], valid_names=['val'],
    callbacks=[lgb.early_stopping(stopping_rounds=30), lgb.log_evaluation(0)],
)
log(f'LTV model best_iteration {model_ltv.best_iteration}, '
    f'mean actual {val_v2.ltv_d30.mean():.2f}, mean predicted {model_ltv.predict(X_val_lgb).mean():.2f}')

# --- Cox retention model (cell 82) ----------------------------------------
# Matches this notebook's cell 82 exactly: no never_activated_flag here,
# scorer.py's extra column at prediction time is silently ignored by
# lifelines (verified), so this doesn't need to change to stay compatible.
cox_features = ['browse_to_chat_latency_minutes', 'n_app_opens_pre_message',
                 'channel_prior_payer_rate_any_revenue', 'is_organic', 'signup_hour_of_day']
cox_data = train_v2.merge(
    survival_data[['user_id', 'duration', 'event_observed']], on='user_id',
)[['duration', 'event_observed'] + cox_features].copy()
cox_data['is_organic'] = cox_data['is_organic'].astype(int)

cph = CoxPHFitter()
cph.fit(cox_data, duration_col='duration', event_col='event_observed')

# --- Save everything the scorer needs (cell 83) ---------------------------
model_lgb.save_model(os.path.join(MODEL_DIR, 'model_payer.txt'))
model_ltv.save_model(os.path.join(MODEL_DIR, 'model_ltv.txt'))
joblib.dump(cph, os.path.join(MODEL_DIR, 'model_retention_cox.pkl'))
channel_priors.to_csv(os.path.join(MODEL_DIR, 'channel_priors.csv'))
joblib.dump(full_cat_cols, os.path.join(MODEL_DIR, 'categorical_cols.pkl'))
joblib.dump(
    {col: X_train_lgb[col].cat.categories.tolist() for col in full_cat_cols},
    os.path.join(MODEL_DIR, 'category_levels.pkl'),
)
log(f'Saved all 6 model files to {MODEL_DIR}')
