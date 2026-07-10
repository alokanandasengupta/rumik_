import os
from typing import Optional

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scorer import IraPreFirstMessageScorer

MODEL_DIR = os.environ.get('MODEL_DIR', os.path.join(os.path.dirname(__file__), 'models'))
REQUIRED_MODEL_FILES = [
    'model_payer.txt', 'model_ltv.txt', 'model_retention_cox.pkl',
    'channel_priors.csv', 'categorical_cols.pkl', 'category_levels.pkl',
]

# Same rule t0_features used in the notebook, minus media_source since the
# form below never collects it, channel alone is what the form has.
ORGANIC_CHANNELS = {'Organic App Store', 'User Invite'}

app = FastAPI(title='Rumik Pre-First-Message Scorer')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)

# Everything lives under /api, this environment's ingress routes only that
# path prefix to this service and sends everything else to the frontend.
api = APIRouter(prefix='/api')

scorer: Optional[IraPreFirstMessageScorer] = None
scorer_error: Optional[str] = None

try:
    scorer = IraPreFirstMessageScorer(model_dir=MODEL_DIR)
except Exception as e:
    scorer_error = str(e)


class ScoreRequest(BaseModel):
    platform: str
    pricing_region_at_signup: str
    creation_source: str
    active_experiment: str
    channel: str
    ad_intent: str
    targeting_age_bucket: str
    targeting_gender: str
    targeting_interest: str
    nudge_experiment_arm: str
    signup_hour_of_day: int = Field(ge=0, le=23)
    signup_day_of_week: int = Field(ge=0, le=6)

    # Pre-message behavior, unknown for a user who hasn't opened the app yet.
    never_activated: bool = True
    browse_to_chat_latency_minutes: float = 0
    n_app_opens_pre_message: int = 0
    pre_message_revenue: float = 0
    saw_plans_pre_message: bool = False
    purchased_pre_message: bool = False


def _missing_model_files():
    return [f for f in REQUIRED_MODEL_FILES if not os.path.isfile(os.path.join(MODEL_DIR, f))]


@api.get('/health')
def health():
    missing = _missing_model_files()
    return {
        'status': 'ok' if scorer is not None else 'models_not_loaded',
        'missing_files': missing,
        'load_error': scorer_error,
    }


@api.get('/options')
def options():
    if scorer is None:
        raise HTTPException(503, 'Models not loaded yet, see /health')
    return {
        'categorical_values': scorer.cat_levels,
        'channels': sorted(scorer.channel_priors.index.tolist()),
    }


@api.post('/score')
def score(req: ScoreRequest):
    if scorer is None:
        raise HTTPException(503, f'Models not loaded: {scorer_error}. See /health.')

    if req.channel not in scorer.channel_priors.index:
        raise HTTPException(
            400,
            f'Unknown channel "{req.channel}". Valid channels: '
            f'{sorted(scorer.channel_priors.index.tolist())}',
        )

    priors = scorer.channel_priors.loc[req.channel]
    is_organic = req.channel in ORGANIC_CHANNELS

    if req.never_activated:
        latency, opens, revenue = 0, 0, 0
        saw_plans, purchased = False, False
    else:
        latency = req.browse_to_chat_latency_minutes
        opens = req.n_app_opens_pre_message
        revenue = req.pre_message_revenue
        saw_plans = req.saw_plans_pre_message
        purchased = req.purchased_pre_message

    user = {
        'platform': req.platform,
        'pricing_region_at_signup': req.pricing_region_at_signup,
        'creation_source': req.creation_source,
        'active_experiment': req.active_experiment,
        'channel': req.channel,
        'ad_intent': req.ad_intent,
        'targeting_age_bucket': req.targeting_age_bucket,
        'targeting_gender': req.targeting_gender,
        'targeting_interest': req.targeting_interest,
        'nudge_experiment_arm': req.nudge_experiment_arm,
        'signup_hour_of_day': req.signup_hour_of_day,
        'signup_day_of_week': req.signup_day_of_week,
        'is_organic': is_organic,
        'channel_prior_payer_rate_subscription': float(priors['payer_rate_subscription']),
        'channel_prior_payer_rate_any_revenue': float(priors['payer_rate_any_revenue']),
        'channel_prior_avg_ltv_d30': float(priors['avg_ltv_d30']),
        'browse_to_chat_latency_minutes': latency,
        'n_app_opens_pre_message': opens,
        'pre_message_revenue': revenue,
        'never_activated_flag': 1 if req.never_activated else 0,
        'saw_plans_pre_message': saw_plans,
        'purchased_pre_message': purchased,
    }

    return scorer.score(user)


app.include_router(api)
