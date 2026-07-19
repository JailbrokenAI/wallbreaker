"""Gate 3 — Property-Based Testing (Hypothesis) for Wallbreaker audit remediation.

Adapted from specs/audit-remediation/pbt-properties.py: all @skip decorators removed and every
property wired against the POST-remediation actual API. Run when all backend security-critical
components are built (M1-backend checkpoint).

Run: pytest -q tests/pbt/test_security_properties.py
"""
from __future__ import annotations

import ipaddress
import os
import string

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_PRIVATE_IPS = st.sampled_from([
    "127.0.0.1", "127.5.5.5", "0.0.0.0", "::1",
    "169.254.169.254", "169.254.170.2",
    "10.0.0.5", "172.16.9.9", "192.168.1.1",
    "fd00::1",
])
_PUBLIC_HOSTS = st.sampled_from(["api.openai.com", "openrouter.ai", "example.com", "8.8.8.8", "1.1.1.1"])
_SCHEMES = st.sampled_from(["http", "https", "file", "ftp", "gopher", "data"])

_path_segments = st.lists(
    st.sampled_from(["a", "b", "sub", "..", ".", "wb_runs", "etc", "passwd", ""]),
    min_size=0, max_size=6,
)
_leading = st.sampled_from(["", "/", "./", "../", "../../", "/etc/", "~"])

# Use a distinct alphabet for secrets vs url so a generated secret can never equal the url
# (avoids a false-positive in the redaction property where the secret coincidentally appears
# in the unredacted url field).
_secret_values = st.text(alphabet=string.printable, min_size=6, max_size=40)
_url_values = st.text(alphabet=string.ascii_letters + string.digits + "/.:-", max_size=30)
_pref_keys = st.text(alphabet=string.ascii_letters + "_", min_size=1, max_size=12)

_SC = [HealthCheck.function_scoped_fixture]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_config(tmp_path):
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    return Config(default_profile="t", profiles={"t": ep}, target=ep,
                  path=tmp_path / "config.toml")


def _auth_headers(token="tok"):
    return {"X-WB-Token": token, "Origin": "http://127.0.0.1:8787"}


# ===========================================================================
# Security Property 1 — Access control (SEC-1/2/3/6/8)
# ===========================================================================

@settings(max_examples=200, deadline=None, suppress_health_check=_SC)
@given(
    token=st.one_of(st.none(), st.text(alphabet=st.characters(max_codepoint=127), max_size=64), st.just("tok")),
    origin=st.one_of(st.none(), st.just("http://127.0.0.1:8787"),
                     st.just("https://evil.example"), st.just("http://evil.example:1234")),
    method=st.sampled_from(["POST", "PUT", "DELETE"]),
)
def test_access_control_invariant(tmp_path, token, origin, method):
    """Unauth/cross-site → 401/403, no side effect."""
    from wallbreaker.dashboard.server import create_app
    from starlette.testclient import TestClient

    c = TestClient(create_app(config=_dummy_config(tmp_path), sessions_dir=tmp_path / "s",
                              require_auth=True, auth_token="tok"),
                   raise_server_exceptions=False)
    headers = {}
    if token is not None:
        headers["X-WB-Token"] = token
    if origin is not None:
        headers["Origin"] = origin

    resp = c.request(method, "/api/fire",
                     json={"request": "x", "max_tokens": 8}, headers=headers)
    authenticated = token == "tok"
    same_origin = origin in (None, "http://127.0.0.1:8787")
    if not (authenticated and same_origin):
        assert resp.status_code in (401, 403), f"unauth/cross-site must be 401/403, got {resp.status_code}"


# ===========================================================================
# Security Property 10 — Token file 0600 (SEC-1)
# ===========================================================================

def test_token_file_is_0600(tmp_path):
    from wallbreaker.dashboard.auth import ensure_launch_token, token_file_path
    tok = ensure_launch_token(str(tmp_path))
    mode = os.stat(token_file_path(str(tmp_path))).st_mode & 0o777
    assert mode == 0o600, f"token file mode {oct(mode)} != 0o600"
    assert len(tok) > 20


# ===========================================================================
# Security Property 2 — Least-privilege tool exposure (SEC-1/4/5)
# ===========================================================================

@settings(max_examples=50, suppress_health_check=_SC)
@given(opt_in=st.booleans())
def test_dashboard_registry_least_privilege(opt_in, tmp_path):
    from wallbreaker.tools.tool_policy import classify, HOST_AFFECTING, build_dashboard_registry
    cfg = _dummy_config(tmp_path)
    reg = build_dashboard_registry(cfg, str(tmp_path), allow_host_tools=opt_in)
    names = set(reg.names())
    host_present = names & HOST_AFFECTING
    if opt_in:
        assert host_present, "opt-in should expose host tools"
    else:
        assert not host_present, f"host tools leaked: {host_present}"
    assert all(classify(n) == "SAFE" for n in (names - HOST_AFFECTING))


# ===========================================================================
# Security Property 3 — SSRF confinement (SEC-4)
# ===========================================================================

def _is_private_or_meta(host: str) -> bool:
    if host in ("metadata.google.internal",):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (ip.is_loopback or ip.is_private or ip.is_link_local
            or ip.is_reserved or ip.is_unspecified)


@settings(max_examples=300, deadline=None)
@given(scheme=_SCHEMES, host=st.one_of(_PRIVATE_IPS, _PUBLIC_HOSTS), port=st.integers(1, 65535))
def test_ssrf_confinement(scheme, host, port):
    from wallbreaker.tools.egress_guard import is_allowed
    url = f"{scheme}://[{host}]:{port}/path" if ":" in host else f"{scheme}://{host}:{port}/path"
    allowed = is_allowed(url)
    if scheme not in ("http", "https"):
        assert not allowed, f"non-http scheme allowed: {url}"
    elif _is_private_or_meta(host):
        assert not allowed, f"private/meta destination allowed: {url}"


def test_ssrf_stable_under_redirect():
    from wallbreaker.tools.egress_guard import validate_redirect_chain
    assert validate_redirect_chain(["https://example.com/a", "http://169.254.169.254/m"]) is False
    assert validate_redirect_chain(["https://example.com/a", "https://openrouter.ai/b"]) is True


# ===========================================================================
# Security Property 4 — Path confinement (SEC-5/10)
# ===========================================================================

@settings(max_examples=300, deadline=None, suppress_health_check=_SC)
@given(leading=_leading, segs=_path_segments)
def test_read_file_path_confinement(tmp_path, leading, segs):
    from wallbreaker.tools.files import _confine
    from wallbreaker.tools.registry import ToolContext
    from wallbreaker.config import Config
    ctx = ToolContext(config=Config(default_profile="x", profiles={}), cwd=str(tmp_path))
    raw = leading + "/".join(s for s in segs if s != "")
    resolved, msg = _confine(ctx, raw)
    inside = str(resolved.resolve()).startswith(str(tmp_path.resolve()))
    assert inside or msg != "", f"path escaped without being flagged: {raw!r} -> {resolved}"


def test_run_log_guard_rejects_symlink(tmp_path):
    from wallbreaker.dashboard.server import _safe_run_path
    outside = tmp_path / "secret.txt"; outside.write_text("s")
    sessions = tmp_path / "sessions"; sessions.mkdir()
    link = sessions / "leak.jsonl"; link.symlink_to(outside)
    assert _safe_run_path(sessions, "leak.jsonl") is None
    assert _safe_run_path(sessions, "../secret") is None


# ===========================================================================
# Security Property 5 — Input validation / no 500 tracebacks (SEC-11)
# ===========================================================================

@settings(max_examples=200, deadline=None, suppress_health_check=_SC)
@given(
    max_rounds=st.one_of(st.integers(), st.text(max_size=8), st.none(),
                         st.floats(allow_nan=False, allow_infinity=False)),
    max_tokens=st.one_of(st.integers(), st.text(max_size=8), st.none()),
)
def test_body_validation_clamps_or_4xx(tmp_path, max_rounds, max_tokens):
    from wallbreaker.dashboard.server import create_app
    from starlette.testclient import TestClient
    c = TestClient(create_app(config=_dummy_config(tmp_path), sessions_dir=tmp_path / "s",
                              require_auth=True, auth_token="tok"),
                   raise_server_exceptions=False)
    resp = c.post("/api/agent/run", headers=_auth_headers(),
                  json={"objective": "x", "max_rounds": max_rounds, "max_tokens": max_tokens})
    assert resp.status_code < 500, f"validation produced 5xx for {max_rounds!r}/{max_tokens!r}"


@given(raw=st.one_of(st.integers(), st.text(max_size=6), st.none(),
                     st.floats(allow_nan=True, allow_infinity=True)),
       default=st.integers(min_value=0, max_value=10))
@settings(max_examples=300)
def test_int_setting_clamps_within_bounds(raw, default):
    from wallbreaker.dashboard.server import _int_setting
    val = _int_setting(raw, default, 1, 50)
    assert 1 <= val <= 50


# ===========================================================================
# Security Property 6 — Data integrity (REL-3/RACE-1, RACE-2)
# ===========================================================================

@settings(max_examples=200, suppress_health_check=_SC)
@given(prefs=st.dictionaries(_pref_keys, st.integers() | st.text(max_size=10), max_size=10))
def test_state_round_trip(tmp_path, prefs):
    from wallbreaker.state import save_state, load_state
    path = tmp_path / ".wallbreaker_state.json"
    save_state(str(path), prefs)
    assert load_state(str(path)) == prefs


@settings(max_examples=200, suppress_health_check=_SC)
@given(
    a=st.dictionaries(_pref_keys, st.integers(), min_size=1, max_size=5),
    b=st.dictionaries(_pref_keys, st.integers(), min_size=1, max_size=5),
)
def test_state_concurrent_merge_preserves_disjoint_keys(tmp_path, a, b):
    from wallbreaker.state import save_state_merge, load_state
    path = tmp_path / ".wallbreaker_state.json"
    save_state_merge(str(path), a)
    save_state_merge(str(path), b)
    merged = load_state(str(path))
    for k, v in a.items():
        if k not in b:
            assert merged.get(k) == v, f"disjoint key {k!r} lost in merge"


@settings(max_examples=100, suppress_health_check=_SC)
@given(puts=st.lists(st.sampled_from(["COMPLIED", "PARTIAL", "REFUSED"]), min_size=1, max_size=30))
def test_cache_count_conservation(tmp_path, puts):
    from wallbreaker.cache import ResultCache
    # Clear any leftover cache from previous Hypothesis examples (tmp_path is shared).
    cache_file = tmp_path / "wb_runs" / "result_cache.jsonl"
    if cache_file.exists():
        cache_file.unlink()
    c1 = ResultCache(str(tmp_path))
    c2 = ResultCache(str(tmp_path))
    for i, bucket in enumerate(puts):
        (c1 if i % 2 == 0 else c2).put("k", bucket, f"r{i}")
    total = ResultCache(str(tmp_path)).get("k")["samples"]
    assert total == len(puts), f"cache count {total} != {len(puts)} puts"


# ===========================================================================
# Security Property 7 — Secret non-exposure (SEC-9)
# ===========================================================================

@settings(max_examples=400)
@given(auth=_secret_values, api_key=_secret_values, password=_secret_values, url=_url_values)
def test_secret_redaction(auth, api_key, password, url):
    from wallbreaker.session import redact_args
    args = {
        "url": url,
        "headers": {"Authorization": f"Bearer {auth}", "x-api-key": api_key},
        "api_key": api_key,
        "password": password,
    }
    redacted = redact_args(args)
    assert auth not in str(redacted.get("headers", {}).get("Authorization", ""))
    assert api_key not in str(redacted.get("headers", {}).get("x-api-key", ""))
    assert api_key not in str(redacted.get("api_key", ""))
    assert password not in str(redacted.get("password", ""))


# ===========================================================================
# Security Property 8 — Concurrency / rate limiting (RACE-3)
# ===========================================================================

@settings(max_examples=50, deadline=None)
@given(limit=st.integers(min_value=1, max_value=8), n=st.integers(min_value=1, max_value=20))
def test_gate_never_exceeds_limit(limit, n):
    import asyncio
    from wallbreaker.providers.request_gate import configure_request_gate, provider_request_slot
    from wallbreaker.config import Endpoint

    configure_request_gate(limit, 0)
    ep = Endpoint("one", "openai", "https://api.example/v1", "m", api_key="k")

    async def run():
        peak = 0
        active = 0

        async def worker():
            nonlocal peak, active
            async with provider_request_slot(ep):
                active += 1
                peak = max(peak, active)
                await asyncio.sleep(0)
                active -= 1

        await asyncio.gather(*(worker() for _ in range(n)))
        return peak

    peak = asyncio.run(run())
    assert peak <= limit, f"gate allowed {peak} concurrent > limit {limit}"


# ===========================================================================
# Stego reversibility — skipped (optional 'stegg' extra)
# ===========================================================================

@pytest.mark.skip(reason="requires the optional 'stegg' dependency")
def test_stego_encrypt_decrypt_reversible():
    pass
