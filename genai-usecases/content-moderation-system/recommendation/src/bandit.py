"""
Stage 2: Thompson-sampling bandit over Beta arms.

Used twice, always on items that already passed the safety gate:
- feed exploration, arms keyed ``"<tier>:<topic>"``, updated by engagement;
- moderator queue, arms keyed ``"queue:<category>"``, updated by moderator overrides.

The bandit only produces a number that is blended into a ranking score. It has no access
to the candidate pool and cannot add or admit an item.
"""

import random
from typing import Callable, Dict, Optional

ArmSaver = Callable[[str, float, float], None]


class ThompsonSamplingBandit:
    """Beta-Bernoulli Thompson sampling with a seeded random source."""

    def __init__(
        self,
        seed: int = 0,
        arms: Optional[Dict[str, Dict[str, float]]] = None,
        on_update: Optional[ArmSaver] = None,
    ):
        self.rng = random.Random(seed)
        self.arms: Dict[str, Dict[str, float]] = {
            key: {"alpha": max(1.0, float(arm["alpha"])), "beta": max(1.0, float(arm["beta"]))}
            for key, arm in (arms or {}).items()
        }
        self.on_update = on_update

    def _arm(self, key: str) -> Dict[str, float]:
        return self.arms.get(key, {"alpha": 1.0, "beta": 1.0})

    def sample(self, key: str) -> float:
        """Draw from the arm's Beta posterior. An unseen arm is uniform on [0, 1]."""
        arm = self._arm(key)
        return self.rng.betavariate(arm["alpha"], arm["beta"])

    def mean(self, key: str) -> float:
        """Posterior mean of the arm; 0.5 for an unseen arm."""
        arm = self._arm(key)
        return arm["alpha"] / (arm["alpha"] + arm["beta"])

    def update(self, key: str, reward: float) -> None:
        """
        Update an arm with a reward in [-1, 1]: positive rewards add to alpha, negative
        ones to beta. Out-of-range rewards are clipped; a zero reward changes nothing.
        """
        reward = max(-1.0, min(1.0, float(reward)))
        if reward == 0.0:
            return
        arm = dict(self._arm(key))
        if reward > 0:
            arm["alpha"] += reward
        else:
            arm["beta"] += -reward
        self.arms[key] = arm
        if self.on_update is not None:
            self.on_update(key, arm["alpha"], arm["beta"])
