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
            if isinstance(arms, dict):
                for key, val in arms.items():
                    self._arms[str(key)] = _Arm(int(val.get("n", 0)), float(val.get("reward", 0.0)))
            else:
                # Accept a list of arm keys (pre-register with zero stats)
                for key in arms:
                    self._arms[str(key)] = _Arm()
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
    return os.path.join(os.path.abspath(cwd or "."), "wb_runs", filename)


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


def context_key(target_family, harm_category) -> str:
    return f"{target_family or '?'}|{harm_category or 'default'}"


def _ctx_key(context) -> str:
    if isinstance(context, (tuple, list)) and len(context) == 2:
        return context_key(context[0], context[1])
    return str(context)


def _read_stats(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            return loaded
    except (OSError, ValueError):
        pass
    return {}


def _write_stats(path: str, data: dict) -> None:
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
    except OSError:
        pass


class ContextualBandit:
    def __init__(self, data=None, seed: int = 0):
        self._ctx: dict[str, dict[str, _Arm]] = {}
        if data:
            for ckey, arms in data.items():
                if not isinstance(arms, dict):
                    continue
                bucket = self._ctx[str(ckey)] = {}
                for arm, val in arms.items():
                    if isinstance(val, dict):
                        bucket[str(arm)] = _Arm(int(val.get("n", 0)), float(val.get("reward", 0.0)))
        self._seed = int(seed)
        self._rng = random.Random(self._seed)

    def _bucket(self, context) -> dict:
        return self._ctx.setdefault(_ctx_key(context), {})

    def update(self, context, arm: str, reward: float) -> "ContextualBandit":
        bucket = self._bucket(context)
        a = bucket.get(arm)
        if a is None:
            a = bucket[arm] = _Arm()
        a.n += 1
        a.reward += _clamp01(reward)
        return self

    def count(self, context, arm: str) -> int:
        a = self._ctx.get(_ctx_key(context), {}).get(arm)
        return a.n if a else 0

    def mean(self, context, arm: str) -> float:
        a = self._ctx.get(_ctx_key(context), {}).get(arm)
        return a.mean if a else 0.0

    def has_stats(self, context) -> bool:
        return any(a.n > 0 for a in self._ctx.get(_ctx_key(context), {}).values())

    def posterior(self, context, arm: str):
        a = self._ctx.get(_ctx_key(context), {}).get(arm, _Arm())
        alpha = a.reward + 1.0
        beta = (a.n - a.reward) + 1.0
        return alpha, beta

    def select(self, context, arms, rng=None):
        seq = list(arms)
        if not seq:
            raise ValueError("select() requires at least one arm")
        gen = rng if rng is not None else self._rng
        bucket = self._ctx.get(_ctx_key(context), {})
        best_arm = seq[0]
        best_sample = -1.0
        for arm in seq:
            a = bucket.get(arm, _Arm())
            alpha = a.reward + 1.0
            beta = (a.n - a.reward) + 1.0
            sample = gen.betavariate(alpha, beta)
            if sample > best_sample:
                best_sample = sample
                best_arm = arm
        return best_arm

    def rank(self, context, arms, rng=None) -> list:
        seq = list(arms)
        gen = rng if rng is not None else self._rng
        bucket = self._ctx.get(_ctx_key(context), {})
        index = {arm: i for i, arm in enumerate(seq)}
        scored = []
        for arm in seq:
            a = bucket.get(arm, _Arm())
            alpha = a.reward + 1.0
            beta = (a.n - a.reward) + 1.0
            scored.append((arm, gen.betavariate(alpha, beta)))
        return [arm for arm, _ in sorted(scored, key=lambda kv: (-kv[1], index[kv[0]]))]

    def to_dict(self) -> dict:
        return {
            ckey: {arm: {"n": a.n, "reward": a.reward} for arm, a in bucket.items()}
            for ckey, bucket in self._ctx.items()
        }

    def save(self, path: str) -> "ContextualBandit":
        data = _read_stats(path)
        for ckey, bucket in self.to_dict().items():
            data[ckey] = bucket
        _write_stats(path, data)
        return self

    @classmethod
    def load(cls, path: str, seed: int = 0) -> "ContextualBandit":
        return cls(_read_stats(path), seed=seed)

    def best_by_context(self, context) -> str | None:
        """Return the arm with the highest posterior mean for this context, or None."""
        bucket = self._ctx.get(_ctx_key(context), {})
        if not bucket:
            return None
        return max(bucket, key=lambda arm: bucket[arm].mean)


# ---------------------------------------------------------------------------
# TG3 — Family-aware bandit helpers (item D / R-D2, R-D3)
# ---------------------------------------------------------------------------

def seed_family_priors(bandit: ContextualBandit, family: str, category: str,
                       priors: dict) -> None:
    """Seed a contextual bandit with empirical family priors if no live data exists yet.

    ``priors`` is a dict[technique -> (wins, total)] from CHANGELOG ASR data.
    Only seeds when the bucket has no live data (≥1 real update), so empirical
    data always overrides the prior without fighting it (R-D2).
    """
    family_priors = priors.get(family, {})
    if not family_priors:
        return
    context = (family, category)
    if bandit.has_stats(context):
        return  # live data already present — don't overwrite
    for technique, (wins, total) in family_priors.items():
        held = max(0.0, total - wins)
        # Inject as real updates so posterior is in the same space as live data.
        for _ in range(int(wins)):
            bandit.update(context, technique, 1.0)
        for _ in range(int(held)):
            bandit.update(context, technique, 0.0)


# ---------------------------------------------------------------------------
# TG5 — Multi-objective campaign bandit (item G / R-G1, R-G4)
# ---------------------------------------------------------------------------

def arm_key(technique: str, transform_chain: str, behavior_category: str) -> str:
    """Canonical string key for a (technique, transform_chain, behavior_category) arm."""
    return f"{technique or '?'}|{transform_chain or ''}|{behavior_category or 'default'}"


def regret_curve(
    rewards_by_step: list[float],
    baseline_rewards_by_step: list[float],
) -> dict:
    """Compute cumulative ASR for the bandit and a random-arm baseline (R-G4).

    Returns::
        {
            "bandit":   list[float],  # cumulative ASR at each step
            "random":   list[float],  # random-arm cumulative ASR at each step
            "beats_random": bool,     # True if bandit ASR > random at the final step
        }
    """
    def cumulative_asr(rewards):
        out = []
        total = hits = 0
        for r in rewards:
            total += 1
            hits += r >= 1.0  # COMPLIED counts as a hit
            out.append(hits / total if total else 0.0)
        return out

    bandit_asr = cumulative_asr(rewards_by_step)
    random_asr = cumulative_asr(baseline_rewards_by_step)
    beats = bandit_asr[-1] > random_asr[-1] if bandit_asr and random_asr else False
    return {"bandit": bandit_asr, "random": random_asr, "beats_random": beats}


def best_technique_by_family(path: str, families=None) -> dict:
    """Return {family: {category: best_technique}} from a saved ContextualBandit file.

    Used by /stats (R-D3) to surface the best technique per family.
    ``families`` defaults to the 6 known families when None.
    """
    known = families or ["openai", "anthropic", "google", "deepseek", "meta", "other"]
    data = _read_stats(path)
    cb = ContextualBandit(data)
    result: dict = {}
    for ckey, bucket in cb._ctx.items():
        if not bucket:
            continue
        # ckey is "family|category"
        parts = ckey.split("|", 1)
        family = parts[0]
        category = parts[1] if len(parts) > 1 else "default"
        if families is not None and family not in families:
            continue
        best = max(bucket, key=lambda arm: bucket[arm].mean) if bucket else None
        if best:
            result.setdefault(family, {})[category] = best
    return result
