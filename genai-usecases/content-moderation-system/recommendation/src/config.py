"""
Configuration flags and settings for the Age-Aware Recommendation System.
"""

import os

# Master Feature Flag
RECOMMENDATION_ENABLED: bool = os.getenv("RECOMMENDATION_ENABLED", "true").lower() == "true"

# Safety Gate Settings
DEFAULT_UNRATED_RATING: str = os.getenv("DEFAULT_UNRATED_RATING", "adult")  # Safe default for legacy unrated items
HIGH_UNCERTAINTY_THRESHOLD: float = float(os.getenv("HIGH_UNCERTAINTY_THRESHOLD", "0.45"))  # Disagreement / low confidence limit

# Escalation Categories (Immediate jump to senior moderator queue, hidden from child/teen)
HIGH_RISK_ESCALATION_CATEGORIES = {
    "violent_extremism",
    "grooming",
    "self_harm",
    "self_harm_promotion",
    "violence",
    "illegal_activity"
}

# Topic lists per age tier
CHILD_SAFE_TOPICS = [
    "education",
    "science",
    "cartoons",
    "crafts",
    "gaming_family",
    "nature",
    "music_kids",
    "sports",
    "animals",
    "puzzles"
]

TEEN_ALLOWED_TOPICS = CHILD_SAFE_TOPICS + [
    "technology",
    "pop_culture",
    "gaming_general",
    "fashion",
    "movies",
    "books",
    "coding",
    "fitness",
    "art"
]

SENSITIVE_TEEN_TOPICS = [
    "dating_advice",
    "mental_health",
    "politics_intro"
]

# Personalization Limits
BORDERLINE_DRIFT_CAP: float = float(os.getenv("BORDERLINE_DRIFT_CAP", "0.15"))  # Max share of borderline content in recent feed
ADULT_DIVERSITY_MIN: float = float(os.getenv("ADULT_DIVERSITY_MIN", "0.20"))   # Min share of exploratory topics for adults
