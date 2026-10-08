"""
Configuration flags and settings for the Age-Aware Recommendation System.

Follows the host project's convention: environment variables read with ``os.getenv`` and
string booleans compared with ``.lower() == "true"``.

Safety note: the only gate setting that can be changed from the environment is the
uncertainty threshold, and it is clamped so it can only be made stricter than the ceiling
below. Rating order, unrated-item handling and the status allow-lists are code, not config.
"""

import os
import logging
from typing import Dict, FrozenSet, Tuple

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    """Read a float from the environment, falling back to the default and clamping to a range."""
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"Invalid value for {name}; using default {default}")
        return default
    if value != value:  # NaN
        logger.warning(f"Invalid value for {name}; using default {default}")
        return default
    return max(minimum, min(maximum, value))


def is_recommendation_enabled() -> bool:
    """Master feature flag. Off unless RECOMMENDATION_ENABLED is exactly 'true'."""
    return os.getenv("RECOMMENDATION_ENABLED", "false").lower() == "true"


# ─── Safety gate ────────────────────────────────────────────────────────────────

# Agent disagreement at or above this value counts as "high uncertainty" for a verified
# child or teen profile. Lower trust levels and stricter parental settings scale it down.
HIGH_UNCERTAINTY_CEILING: float = 0.45
HIGH_UNCERTAINTY_THRESHOLD: float = _env_float(
    "HIGH_UNCERTAINTY_THRESHOLD", HIGH_UNCERTAINTY_CEILING, 0.05, HIGH_UNCERTAINTY_CEILING
)

# Toxicity cut-offs used when deriving an audience rating.
TOXICITY_BLOCK_THRESHOLD: float = 0.75
TOXICITY_ADULT_THRESHOLD: float = 0.35
TOXICITY_TEEN_THRESHOLD: float = 0.10

# Statuses that mean the item was taken down or its author sanctioned. Never served.
BLOCKED_STATUSES: FrozenSet[str] = frozenset(
    {"removed", "blocked", "banned", "user_banned", "user_suspended"}
)

# The only status a child or teen (or a self-declared adult) may be served.
APPROVED_STATUS: str = "approved"

# Statuses an adult with parent-linked or verified age may additionally be served.
ADULT_SERVABLE_STATUSES: FrozenSet[str] = frozenset({"approved", "warned"})

# Escalation categories: hidden from child and teen feeds immediately and sent to the
# front of the senior-moderator queue. Each category lists stems that are matched as
# substrings of a label with all separators removed, so spelling variants such as
# "selfharm", "self harm promotion" or "violent extremist" are caught. Over-matching
# (for example "bridegroom") only hides an item from minors, which is the safe direction.
HIGH_RISK_ESCALATION_STEMS: Dict[str, Tuple[str, ...]] = {
    "violent_extremism": ("extremis", "terror", "radicali"),
    "grooming": ("groom", "childsafety", "childexploit", "childsexual", "csam"),
    "self_harm": ("selfharm", "selfinjur", "suicid", "eatingdisorder"),
}
HIGH_RISK_ESCALATION_CATEGORIES: FrozenSet[str] = frozenset(HIGH_RISK_ESCALATION_STEMS)

# Policy-violation labels that still allow a `teen` rating. Every other label, including
# labels this module has never seen, rates the item `adult`.
TEEN_TOLERATED_VIOLATIONS: FrozenSet[str] = frozenset({"spam", "copyright"})

# Entries in a violations list that mean "no violation".
NO_VIOLATION_LABELS: FrozenSet[str] = frozenset({"none", "no_violation", "no_violations"})

# Violation severities that still allow a rating below `adult`.
SEVERITY_ALL_AGES: FrozenSet[str] = frozenset({"none"})
SEVERITY_TEEN: FrozenSet[str] = frozenset({"none", "low"})

# ─── Topic lists per age tier ───────────────────────────────────────────────────

CHILD_SAFE_TOPICS: Tuple[str, ...] = (
    "education",
    "science",
    "cartoons",
    "crafts",
    "gaming_family",
    "nature",
    "music_kids",
    "sports",
    "animals",
    "puzzles",
)

TEEN_ALLOWED_TOPICS: Tuple[str, ...] = CHILD_SAFE_TOPICS + (
    "technology",
    "pop_culture",
    "gaming_general",
    "fashion",
    "movies",
    "books",
    "coding",
    "fitness",
    "art",
)

# Teen-rated topics that a teen only sees when a parent has allowed the topic.
SENSITIVE_TEEN_TOPICS: Tuple[str, ...] = (
    "dating_advice",
    "mental_health",
    "politics_intro",
)

# ─── Personalization limits ─────────────────────────────────────────────────────

BORDERLINE_DRIFT_CAP: float = _env_float("BORDERLINE_DRIFT_CAP", 0.15, 0.0, 0.5)
ADULT_DIVERSITY_MIN: float = _env_float("ADULT_DIVERSITY_MIN", 0.20, 0.0, 0.5)
