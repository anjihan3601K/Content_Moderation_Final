"""The hook the host moderation workflow calls: off by default, never raises."""

import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

workflow = pytest.importorskip("src.agents.workflow")


def _state():
    return {
        "content_id": "c1",
        "status": "approved",
        "moderation_action": "approved",
        "content_removed": False,
        "toxicity_score": 0.01,
        "policy_violations": [],
        "policy_flags": [],
        "violation_severity": "none",
        "contains_sensitive_content": False,
        "explicit_content_detected": False,
        "hate_speech_detected": False,
        "harassment_detected": False,
        "media_risk_level": "none",
        "content_category": "science",
        "content_topics": ["science"],
        "agent_decisions": [
            {"agent_name": "Content Analysis Agent", "decision": "approve", "confidence": 0.85},
        ],
    }


def test_hook_leaves_state_untouched_when_flag_off(monkeypatch):
    monkeypatch.delenv("RECOMMENDATION_ENABLED", raising=False)
    state = _state()
    workflow._apply_audience_rating(state)
    assert state == _state()


def test_hook_rates_state_when_flag_on(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    state = _state()
    workflow._apply_audience_rating(state)
    assert state["audience_rating"] == "all_ages"
    assert state["agent_disagreement"] == 0.0


def test_hook_swallows_rating_failures(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    import recommendation.src.rating as rating

    def boom(state):
        raise RuntimeError("rating failed")

    monkeypatch.setattr(rating, "apply_audience_rating", boom)
    state = _state()
    workflow._apply_audience_rating(state)
    assert "audience_rating" not in state


def test_hook_tolerates_missing_state(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    workflow._apply_audience_rating(None)
