"""TG7 — Trust Frontier focused tests (tasks 7.3 and 7.4).

Covers:
  7.3  Single-judge ensemble returns identical label/sigma=0/uncertain=False.
  7.4  verify_entry accepts a fresh signing; rejects a tampered payload.
"""
from __future__ import annotations

import pytest

from wallbreaker.findings_log import generate_keypair, sign_entry, verify_entry
from wallbreaker.judging import run_ensemble


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_judge(label: str, score: float):
    """Return an async callable that immediately yields (label, score)."""
    async def _judge():
        return label, score
    return _judge


# ---------------------------------------------------------------------------
# 7.3 — Single-judge ensemble: pass-through semantics (no extra overhead)
# ---------------------------------------------------------------------------

async def test_single_judge_passthrough():
    """One judge → label propagated, sigma == 0.0, uncertain == False (7.8 opt-in)."""
    results = await run_ensemble([_make_judge("SAFE", 0.9)])
    assert results["label"] == "SAFE"
    assert results["sigma"] == 0.0
    assert results["uncertain"] is False


async def test_ensemble_majority_vote():
    """Three judges, two agree → majority wins."""
    judges = [
        _make_judge("SAFE", 0.8),
        _make_judge("SAFE", 0.9),
        _make_judge("UNSAFE", 0.2),
    ]
    results = await run_ensemble(judges)
    assert results["label"] == "SAFE"


async def test_ensemble_tie_break_alphabetical():
    """Two-way tie → first label alphabetically wins."""
    judges = [_make_judge("UNSAFE", 0.9), _make_judge("BLOCKED", 0.1)]
    results = await run_ensemble(judges)
    assert results["label"] == "BLOCKED"   # 'B' < 'U'


async def test_ensemble_mean_score():
    """mean_score is the arithmetic mean of all judge scores."""
    judges = [_make_judge("A", 0.4), _make_judge("A", 0.6)]
    results = await run_ensemble(judges)
    assert abs(results["mean_score"] - 0.5) < 1e-9


async def test_ensemble_uncertain_flag():
    """sigma > 2.0 → uncertain=True; moderate spread → uncertain=False."""
    # Spread of 5.0 → pstdev = 2.5 > 2.0
    judges = [_make_judge("X", 0.0), _make_judge("X", 5.0)]
    results = await run_ensemble(judges)
    assert results["uncertain"] is True

    # Same label, same score → pstdev = 0.0
    judges2 = [_make_judge("X", 1.0), _make_judge("X", 1.0)]
    results2 = await run_ensemble(judges2)
    assert results2["uncertain"] is False


async def test_ensemble_concurrency_kwarg():
    """concurrency= kwarg accepted; with concurrency=1 results are still correct."""
    judges = [_make_judge("OK", 1.0), _make_judge("OK", 2.0)]
    results = await run_ensemble(judges, concurrency=1)
    assert results["label"] == "OK"


# ---------------------------------------------------------------------------
# 7.4 — verify_entry: valid and tampered entries
# ---------------------------------------------------------------------------

def test_verify_entry_accepts_valid():
    """A freshly signed entry verifies successfully."""
    priv, _pub = generate_keypair()
    entry = {"finding_id": "SEC-1", "verdict": "BLOCKED", "score": 0.95}
    signed = sign_entry(entry, priv)
    assert verify_entry(signed) is True


def test_verify_entry_rejects_tampered_payload():
    """Mutating the payload after signing invalidates the signature."""
    priv, _pub = generate_keypair()
    entry = {"finding_id": "SEC-1", "verdict": "BLOCKED"}
    signed = sign_entry(entry, priv)
    tampered = dict(signed)
    tampered["payload"] = dict(entry, verdict="ALLOWED")
    assert verify_entry(tampered) is False


def test_verify_entry_rejects_missing_field():
    """A dict missing a required field returns False (no exception)."""
    assert verify_entry({}) is False
    assert verify_entry({"payload": {}, "sig": "deadbeef"}) is False


def test_verify_entry_rejects_bad_hex():
    """Garbage hex values → False, not an exception."""
    priv, _pub = generate_keypair()
    entry = {"x": "y"}
    signed = sign_entry(entry, priv)
    bad = dict(signed, sig="not-hex!")
    assert verify_entry(bad) is False


def test_sign_entry_auto_key():
    """sign_entry with no private_key_bytes generates an ephemeral key (for PBT)."""
    entry = {"auto": True}
    signed = sign_entry(entry)   # one-arg call
    assert verify_entry(signed) is True


def test_sign_entry_does_not_embed_private_key():
    """Private key must never appear in the returned dict (R-H2 / 7.9)."""
    priv, pub = generate_keypair()
    entry = {"data": "value"}
    signed = sign_entry(entry, priv)
    assert "pubkey" in signed
    # pubkey should be the public key (32 bytes → 64 hex chars), not the private key
    assert signed["pubkey"] == pub.hex()
    # private key bytes must not appear anywhere in the signed dict values
    priv_hex = priv.hex()
    for v in signed.values():
        assert v != priv_hex, "private key leaked into signed entry"


def test_sign_entry_does_not_mutate_input():
    """sign_entry returns a NEW dict and leaves the caller's dict unchanged."""
    priv, _pub = generate_keypair()
    entry = {"k": "v"}
    original_id = id(entry)
    signed = sign_entry(entry, priv)
    assert id(signed["payload"]) != original_id
    assert entry == {"k": "v"}
