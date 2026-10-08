"""Shared pytest setup for the recommendation tests. No network, no real databases."""

import sys
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recommendation.src.models import (  # noqa: E402
    AgeTier,
    AgeTrustLevel,
    AudienceRating,
    ParentalControls,
    RecommendationItemModel,
    ViewerProfileModel,
)


def make_item(**overrides: Any) -> RecommendationItemModel:
    """An approved, all-ages, low-uncertainty item; override fields per test."""
    fields = dict(
        item_id="item-1",
        content_text="placeholder text",
        content_category="science",
        content_topics=["science"],
        audience_rating=AudienceRating.ALL_AGES,
        toxicity_score=0.01,
        overall_confidence=0.9,
        agent_disagreement=0.0,
        status="approved",
    )
    fields.update(overrides)
    return RecommendationItemModel(**fields)


def make_profile(
    tier: AgeTier = AgeTier.CHILD,
    trust: AgeTrustLevel = AgeTrustLevel.VERIFIED,
    **overrides: Any,
) -> ViewerProfileModel:
    """A viewer profile; parental controls can be passed as a dict."""
    controls = overrides.pop("parental_controls", None) or {}
    if isinstance(controls, dict):
        controls = ParentalControls(**controls)
    return ViewerProfileModel(
        profile_id=overrides.pop("profile_id", "profile-1"),
        age_tier=tier,
        age_trust_level=trust,
        parental_controls=controls,
        **overrides,
    )


@pytest.fixture
def item_factory():
    return make_item


@pytest.fixture
def profile_factory():
    return make_profile


# ─── storage fixtures (Stage 2 and 3) ───────────────────────────────────────────

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(PROJECT_ROOT / "recommendation" / "evaluation"))

from fakes import FakeFirestoreClient  # noqa: E402
from recommendation.src.store import (  # noqa: E402
    DualDocumentStore,
    FirestoreDocumentStore,
    RecommendationRepository,
    SQLiteDocumentStore,
)

BACKENDS = ["sqlite", "firestore", "dual"]


def make_store(backend: str, tmp_path):
    if backend == "sqlite":
        return SQLiteDocumentStore(str(tmp_path / "rec.db"))
    if backend == "firestore":
        return FirestoreDocumentStore(FakeFirestoreClient())
    return DualDocumentStore(
        SQLiteDocumentStore(str(tmp_path / "rec.db")), FirestoreDocumentStore(FakeFirestoreClient())
    )


@pytest.fixture(params=BACKENDS)
def repository(request, tmp_path):
    """A repository on each storage backend in turn."""
    return RecommendationRepository(make_store(request.param, tmp_path))


@pytest.fixture
def sqlite_repository(tmp_path):
    return RecommendationRepository(SQLiteDocumentStore(str(tmp_path / "rec.db")))


@pytest.fixture(scope="session")
def mock_repository():
    """
    The full mock dataset, loaded once. Tests must not modify it. Held in the in-memory
    Firestore fake because loading 1,080 documents into SQLite one commit at a time is
    slow; SQLite behaviour is covered by test_rec_store.py.
    """
    from gate_harness import load_mock_data

    repo = RecommendationRepository(FirestoreDocumentStore(FakeFirestoreClient()))
    load_mock_data(repo)
    return repo
