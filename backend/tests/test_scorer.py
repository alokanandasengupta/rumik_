"""
Unit tests for IraPreFirstMessageScorer's pure logic (scorer.py), plus
integration tests against the real trained model artifacts committed in
models/ (model_payer.txt, model_ltv.txt, model_retention_cox.pkl, etc.) --
these are small, real files, not mocks, so a change that actually breaks
scoring (a schema mismatch, a corrupted artifact) fails here for real.
"""
import os

import pytest

from scorer import IraPreFirstMessageScorer

MODEL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")


@pytest.fixture(scope="module")
def scorer():
    return IraPreFirstMessageScorer(model_dir=MODEL_DIR)


BASE_USER = {
    "platform": "ios",
    "pricing_region_at_signup": "IN",
    "creation_source": "organic",
    "active_experiment": "none",
    "channel": "Meta Ads",
    "ad_intent": "conversion",
    "targeting_age_bucket": "25-34",
    "targeting_gender": "all",
    "targeting_interest": "general",
    "nudge_experiment_arm": "control",
    "signup_hour_of_day": 14,
    "signup_day_of_week": 2,
    "is_organic": False,
    "channel_prior_payer_rate_subscription": 0.0416,
    "channel_prior_payer_rate_any_revenue": 0.0956,
    "channel_prior_avg_ltv_d30": 10.0516,
    "browse_to_chat_latency_minutes": 0,
    "n_app_opens_pre_message": 0,
    "pre_message_revenue": 0,
    "never_activated_flag": 1,
    "saw_plans_pre_message": False,
    "purchased_pre_message": False,
}


class TestSignalWeight:
    """_signal_weight is pure and doesn't need the trained models at all."""

    def test_never_activated_gets_floor_weight(self, scorer):
        user = {**BASE_USER, "never_activated_flag": 1}
        assert scorer._signal_weight(user) == 0.05

    def test_activated_with_zero_signal_gets_base_weight(self, scorer):
        user = {**BASE_USER, "never_activated_flag": 0,
                 "n_app_opens_pre_message": 0, "browse_to_chat_latency_minutes": 0}
        assert scorer._signal_weight(user) == pytest.approx(0.20)

    def test_activated_at_full_signal_gets_max_weight(self, scorer):
        user = {**BASE_USER, "never_activated_flag": 0,
                 "n_app_opens_pre_message": scorer.OPENS_CAP,
                 "browse_to_chat_latency_minutes": scorer.LATENCY_CAP}
        assert scorer._signal_weight(user) == pytest.approx(scorer.MAX_WEIGHT)

    def test_signal_strength_is_capped_not_extrapolated(self, scorer):
        # opens far beyond the cap shouldn't push weight past MAX_WEIGHT
        user = {**BASE_USER, "never_activated_flag": 0,
                 "n_app_opens_pre_message": scorer.OPENS_CAP * 50,
                 "browse_to_chat_latency_minutes": scorer.LATENCY_CAP * 50}
        assert scorer._signal_weight(user) == pytest.approx(scorer.MAX_WEIGHT)

    def test_weight_is_monotonic_in_opens(self, scorer):
        low = {**BASE_USER, "never_activated_flag": 0, "n_app_opens_pre_message": 0}
        high = {**BASE_USER, "never_activated_flag": 0, "n_app_opens_pre_message": scorer.OPENS_CAP}
        assert scorer._signal_weight(high) > scorer._signal_weight(low)


class TestScoreIntegration:
    """Exercises the real committed model artifacts end to end."""

    def test_score_returns_expected_shape(self, scorer):
        result = scorer.score(BASE_USER)
        assert set(result.keys()) == {
            "payer_probability", "signal_weight_used",
            "predicted_ltv_d30_inr", "retention_probability",
        }
        assert set(result["retention_probability"].keys()) == {"day_1", "day_7", "day_14", "day_30"}

    def test_payer_probability_is_a_valid_probability(self, scorer):
        result = scorer.score(BASE_USER)
        assert 0.0 <= result["payer_probability"] <= 1.0

    def test_retention_survival_is_monotonically_non_increasing(self, scorer):
        # A survival curve can never increase over time -- day_30 retention
        # can't exceed day_1. This is the property that would catch a
        # genuinely broken/misaligned Cox model.
        r = scorer.score(BASE_USER)["retention_probability"]
        assert r["day_1"] >= r["day_7"] >= r["day_14"] >= r["day_30"]
        for v in r.values():
            assert 0.0 <= v <= 1.0

    def test_predicted_ltv_is_non_negative(self, scorer):
        result = scorer.score(BASE_USER)
        assert result["predicted_ltv_d30_inr"] >= 0

    def test_never_activated_user_relies_mostly_on_channel_prior(self, scorer):
        # never_activated_flag=1 forces signal_weight to 0.05, so the
        # blended probability should sit close to the channel's raw prior.
        result = scorer.score(BASE_USER)
        prior = BASE_USER["channel_prior_payer_rate_any_revenue"]
        assert abs(result["payer_probability"] - prior) < 0.15
