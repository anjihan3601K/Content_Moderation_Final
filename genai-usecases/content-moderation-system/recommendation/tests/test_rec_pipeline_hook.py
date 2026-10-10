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
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "false")
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
    import recommendation.src.integration as integration

    def boom(state):
        raise RuntimeError("rating failed")

    monkeypatch.setattr(integration, "on_moderation_complete", boom)
    state = _state()
    workflow._apply_audience_rating(state)
    assert "audience_rating" not in state


def test_hook_tolerates_missing_state(monkeypatch):
    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    workflow._apply_audience_rating(None)


def test_hook_stores_the_rated_item_when_a_repository_is_registered(monkeypatch, sqlite_repository):
    import recommendation.src.integration as integration

    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    integration.set_repository(sqlite_repository)
    try:
        workflow._apply_audience_rating(_state())
    finally:
        integration.set_repository(None)
    stored = sqlite_repository.get_item("c1")
    assert stored.audience_rating.value == "all_ages"
    assert stored.agent_disagreement == 0.0 and stored.overall_confidence == 0.85


def test_hook_stores_nothing_when_the_flag_is_off(monkeypatch, sqlite_repository):
    import recommendation.src.integration as integration

    monkeypatch.setenv("RECOMMENDATION_ENABLED", "false")
    integration.set_repository(sqlite_repository)
    try:
        workflow._apply_audience_rating(_state())
    finally:
        integration.set_repository(None)
    assert sqlite_repository.list_items() == []


def test_hook_survives_a_storage_failure(monkeypatch):
    import recommendation.src.integration as integration

    class BrokenRepository:
        def upsert_item(self, item):
            raise OSError("disk full")

    monkeypatch.setenv("RECOMMENDATION_ENABLED", "true")
    integration.set_repository(BrokenRepository())
    try:
        state = _state()
        workflow._apply_audience_rating(state)
    finally:
        integration.set_repository(None)
    assert state["audience_rating"] == "all_ages"
