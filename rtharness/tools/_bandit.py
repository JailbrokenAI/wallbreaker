from __future__ import annotations

import json
import math
import os
import random
from dataclasses import dataclass

STATS_FILENAME = "technique_stats.json"
DEFAULT_C = math.sqrt(2.0)


@dataclass
class _Arm:
    n: int = 0
    reward: float = 0.0

    @property
    def mean(self) -> float:
        return self.reward / self.n if self.n else 0.0


def _clamp01(x: float) -> float:
    x = float(x)
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class Bandit:
    def __init__(self, arms=None, c: float = DEFAULT_C, rng=None):
        self._arms: dict[str, _Arm] = {}
        if arms:
            for key, val in arms.items():
                self._arms[str(key)] = _Arm(int(val.get("n", 0)), float(val.get("reward", 0.0)))
        self._c = float(c)
        self._rng = rng

    def update(self, arm: str, reward: float) -> "Bandit":
        a = self._arms.get(arm)
        if a is None:
            a = self._arms[arm] = _Arm()
        a.n += 1
        a.reward += _clamp01(reward)
        return self

    def count(self, arm: str) -> int:
        a = self._arms.get(arm)
        return a.n if a else 0

    def mean(self, arm: str) -> float:
        a = self._arms.get(arm)
        return a.mean if a else 0.0

    def has_stats(self) -> bool:
        return any(a.n > 0 for a in self._arms.values())

    def _ucb(self, arm: str, total: int) -> float:
        a = self._arms.get(arm)
        if a is None or a.n == 0:
            return math.inf
        return a.mean + self._c * math.sqrt(math.log(max(1, total)) / a.n)

    def ucb_scores(self, arms) -> dict[str, float]:
        total = max(1, sum(self.count(x) for x in arms))
        return {arm: self._ucb(arm, total) for arm in arms}

    def select(self, arms):
        seq = list(arms)
        if not seq:
            raise ValueError("select() requires at least one arm")
        scores = self.ucb_scores(seq)
        best = max(scores[a] for a in seq)
        for arm in seq:
            if scores[arm] == best:
                return arm
        return seq[0]

    def rank(self, arms) -> list:
        seq = list(arms)
        scores = self.ucb_scores(seq)
        index = {arm: i for i, arm in enumerate(seq)}
        return sorted(seq, key=lambda a: (-scores[a], index[a]))

    def thompson_select(self, arms, rng=None):
        seq = list(arms)
        if not seq:
            raise ValueError("thompson_select() requires at least one arm")
        gen = rng or self._rng or random.Random(0)
        best_arm = seq[0]
        best_sample = -1.0
        for arm in seq:
            a = self._arms.get(arm, _Arm())
            alpha = a.reward + 1.0
            beta = (a.n - a.reward) + 1.0
            sample = gen.betavariate(alpha, beta)
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        return best_arm

    def stats(self) -> dict:
        return {key: {"n": a.n, "reward": a.reward} for key, a in self._arms.items()}


def stats_path(cwd: str = ".", filename: str = STATS_FILENAME) -> str:
    return os.path.join(os.path.abspath(cwd or "."), "rth_runs", filename)


def _key(target_model, category) -> str:
    return f"{target_model or '?'}|{category or 'default'}"


class BanditStore:
    def __init__(self, path: str, c: float = DEFAULT_C):
        self.path = path
        self._c = float(c)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self._data = loaded
        except (OSError, ValueError):
            self._data = {}

    def bandit(self, target_model, category) -> Bandit:
        arms = self._data.get(_key(target_model, category), {})
        return Bandit(arms, c=self._c)

    def save(self, target_model, category, bandit: Bandit) -> "BanditStore":
        self._data[_key(target_model, category)] = bandit.stats()
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2, sort_keys=True)
        except OSError:
            pass
        return self
