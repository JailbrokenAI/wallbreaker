"""Effective timeout resolution (audit P1-4) — timeout=0 must not mean 0s."""

from __future__ import annotations

from wallbreaker.config import Endpoint
from wallbreaker.providers.base import DEFAULT_TIMEOUT, resolve_timeout
from wallbreaker.providers.factory import build_provider


def test_resolve_timeout_zero_uses_default():
    assert resolve_timeout(0) == DEFAULT_TIMEOUT
    assert resolve_timeout(0.0, None) == DEFAULT_TIMEOUT
    assert resolve_timeout(None, None) == DEFAULT_TIMEOUT


def test_resolve_timeout_endpoint_wins_when_positive():
    assert resolve_timeout(90, 30) == 90.0
    assert resolve_timeout(0, 45) == 45.0
    assert resolve_timeout(0, 0, default=99) == 99.0


def test_endpoint_effective_timeout():
    ep = Endpoint(name="t", protocol="openai", base_url="http://x", model="m", timeout=0.0)
    assert ep.effective_timeout() == DEFAULT_TIMEOUT
    ep2 = Endpoint(name="t", protocol="openai", base_url="http://x", model="m", timeout=30.0)
    assert ep2.effective_timeout() == 30.0
    assert ep2.effective_timeout(override=10) == 30.0  # endpoint >0 wins first


def test_build_provider_uses_resolved_timeout():
    ep = Endpoint(
        name="t",
        protocol="openai",
        base_url="http://x",
        model="m",
        api_key="k",
        timeout=0.0,
    )
    p = build_provider(ep)
    assert p.timeout == DEFAULT_TIMEOUT
    p2 = build_provider(ep, timeout=200)
    assert p2.timeout == 200.0
