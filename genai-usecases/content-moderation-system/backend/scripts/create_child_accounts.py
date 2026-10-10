"""
Create demo child and teen accounts for the age-aware "For You" feed.

    backend/.venv/Scripts/python.exe backend/scripts/create_child_accounts.py

Each account is an ordinary "user" login plus a recommender profile with a verified age
group and a few interests. Running it again changes nothing for accounts that exist.
"""

import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT.parent))

from src.database.auth_db import AuthDatabase  # noqa: E402

from recommendation.src.api import build_container  # noqa: E402
from recommendation.src.models import AgeTier, AgeTrustLevel, ViewerProfileModel  # noqa: E402
from recommendation.src.personalization import TierTopicGuard  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

DEMO_ACCOUNTS = [
    {"username": "child1", "password": "child@123", "full_name": "Aarav (age 9)", "tier": AgeTier.CHILD,
     "interests": ["science", "animals"]},
    {"username": "child2", "password": "child@123", "full_name": "Diya (age 11)", "tier": AgeTier.CHILD,
     "interests": ["cartoons", "puzzles", "sports"]},
    {"username": "child3", "password": "child@123", "full_name": "Kabir (age 8)", "tier": AgeTier.CHILD,
     "interests": ["nature", "crafts"]},
    {"username": "teen1", "password": "teen@123", "full_name": "Meera (age 15)", "tier": AgeTier.TEEN,
     "interests": ["coding", "technology", "sports"]},
]


def create_child_accounts():
    """Create the demo logins and their age-group profiles."""
    auth_db = AuthDatabase()
    repository = build_container().repository

    for account in DEMO_ACCOUNTS:
        created = auth_db.create_user(
            username=account["username"], password=account["password"],
            full_name=account["full_name"], role="user",
        )
        user = auth_db.get_user_by_username(account["username"])
        profile_id = str(user["user_id"])

        profile = repository.get_profile(profile_id)
        if created or not profile.tier_declared:
            profile = ViewerProfileModel(
                profile_id=profile_id, user_id=profile_id, age_tier=account["tier"],
                age_trust_level=AgeTrustLevel.VERIFIED, tier_declared=True,
            )
            profile.explicit_interests = TierTopicGuard.validate_explicit_interests(profile, account["interests"])
            repository.save_profile(profile)

        stored = repository.get_profile(profile_id)
        logger.info(
            f"[{'+' if created else '-'}] {account['username']:<8} password: {account['password']:<10} "
            f"age group: {stored.age_tier.value:<6} interests: {', '.join(stored.explicit_interests)}"
        )


if __name__ == "__main__":
    create_child_accounts()
