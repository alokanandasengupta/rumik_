"""
API-level tests for app.py, using FastAPI's TestClient against the real
scorer (loaded from the committed model artifacts) -- no mocking of the
scoring pipeline itself, only HTTP-layer behavior is under test here.
"""
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)

VALID_PAYLOAD = {
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
}


def test_health_reports_models_loaded():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["missing_files"] == []


def test_options_lists_known_channels():
    resp = client.get("/api/options")
    assert resp.status_code == 200
    channels = resp.json()["channels"]
    assert "Meta Ads" in channels
    assert "Organic App Store" in channels


def test_score_valid_payload_returns_200_with_expected_fields():
    resp = client.post("/api/score", json=VALID_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["payer_probability"] <= 1.0
    assert set(body["retention_probability"].keys()) == {"day_1", "day_7", "day_14", "day_30"}


def test_score_unknown_channel_returns_400():
    resp = client.post("/api/score", json={**VALID_PAYLOAD, "channel": "Carrier Pigeon"})
    assert resp.status_code == 400
    assert "Unknown channel" in resp.json()["detail"]


def test_score_missing_required_field_returns_422():
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "channel"}
    resp = client.post("/api/score", json=payload)
    assert resp.status_code == 422


def test_score_signup_hour_out_of_range_returns_422():
    resp = client.post("/api/score", json={**VALID_PAYLOAD, "signup_hour_of_day": 25})
    assert resp.status_code == 422


def test_never_activated_defaults_zero_out_pre_message_signal():
    # never_activated defaults to True, and the endpoint should force
    # latency/opens/revenue to 0 regardless of what else is sent, since a
    # user who never activated can't have real pre-message behavior.
    resp = client.post("/api/score", json={
        **VALID_PAYLOAD,
        "never_activated": True,
        "n_app_opens_pre_message": 50,  # should be ignored server-side
    })
    assert resp.status_code == 200
    # signal_weight_used should reflect the never-activated floor (0.05),
    # not a weight influenced by the (ignored) opens value.
    assert resp.json()["signal_weight_used"] == 0.05
