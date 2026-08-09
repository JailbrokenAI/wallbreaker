"""Parameterizable PBT property factories for agent_dashboard_harden consumers.

Each factory returns a Hypothesis-decorated test function. The caller supplies
their own function under test; the factory provides the strategy and the
property assertion. Wire these in your project's conftest.py or test file.

Usage in a consuming project's conftest.py or test file::

    from agent_dashboard_harden.pbt_fixtures import (
        make_access_control_property,
        make_input_validation_property,
        make_data_integrity_property,
        make_corpus_integrity_property,
        make_session_property,
    )

    # SP-1: auth_fn(token, origin, method) -> int (HTTP status)
    test_my_access_control = make_access_control_property(my_auth_fn)

    # SP-2: validate_fn(url) -> None (raises EgressBlocked on invalid)
    test_my_input_validation = make_input_validation_property(my_validate_fn)

    # SP-3: sign_fn(entry) -> signed; verify_fn(signed) -> bool
    test_my_data_integrity = make_data_integrity_property(my_sign, my_verify)

    # SP-4: verify_sha_fn(pinned, actual) -> bool
    test_my_corpus_integrity = make_corpus_integrity_property(my_sha_fn)

    # SP-5: token_fn(tmp_path) -> Path
    test_my_session = make_session_property(my_token_fn)
"""
from __future__ import annotations

import string
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Shared strategies (mirrors pbt-properties.py)
# ---------------------------------------------------------------------------
_TOKENS = st.one_of(
    st.none(),
    st.text(alphabet=st.characters(max_codepoint=127), max_size=64),
)
_ORIGINS = st.one_of(
    st.none(),
    st.just("http://127.0.0.1:8787"),
    st.just("https://evil.example"),
    st.just("http://evil.example:1234"),
)
_METHODS = st.sampled_from(["POST", "PUT", "DELETE"])

_SCHEMES = st.sampled_from(["http", "https", "file", "ftp", "gopher", "data"])
_HOSTS = st.sampled_from([
    "api.openai.com", "openrouter.ai", "example.com",
    "metadata.google.internal", "127.0.0.1", "169.254.169.254",
])

_DICT_KEYS = st.text(alphabet=string.ascii_letters, min_size=1, max_size=8)
_DICT_VALS = st.text(max_size=40)
_SHA = st.text(alphabet="0123456789abcdef", min_size=40, max_size=40)

_SC = [HealthCheck.function_scoped_fixture]


# ---------------------------------------------------------------------------
# SP-1 — Access control
# ---------------------------------------------------------------------------

def make_access_control_property(auth_fn, *, max_examples: int = 400):
    """Return a Hypothesis test that verifies *auth_fn* rejects unauth/cross-site requests.

    ``auth_fn(token: str | None, origin: str | None, method: str) -> int``
    must return an HTTP status code.

    Property: ∀ (token, origin) that are not the expected valid pair
    → status ∈ {401, 403}.
    """

    @settings(max_examples=max_examples, deadline=None, suppress_health_check=_SC)
    @given(token=_TOKENS, origin=_ORIGINS, method=_METHODS)
    def _test(token, origin, method):
        status = auth_fn(token, origin, method)
        authorized = (token == "tok") and (origin in (None, "http://127.0.0.1:8787"))
        if not authorized:
            assert status in (401, 403), (
                f"unauth/cross-site request returned {status} for "
                f"token={token!r}, origin={origin!r}, method={method!r}"
            )

    _test.__name__ = "test_access_control_property"
    return _test


# ---------------------------------------------------------------------------
# SP-2 — Input validation
# ---------------------------------------------------------------------------

def make_input_validation_property(validate_fn, *, max_examples: int = 300):
    """Return a Hypothesis test that verifies *validate_fn* never raises unexpectedly.

    ``validate_fn(url: str) -> None``
    must raise only ``EgressBlocked`` (or a subclass thereof) on invalid input,
    never an unexpected exception.

    Property: ∀ (scheme, host) → validate_fn raises only EgressBlocked or nothing.
    """
    from agent_dashboard_harden import EgressBlocked

    @settings(max_examples=max_examples, suppress_health_check=_SC)
    @given(scheme=_SCHEMES, host=_HOSTS)
    def _test(scheme, host):
        url = f"{scheme}://{host}/path"
        try:
            validate_fn(url)
        except EgressBlocked:
            pass  # expected on blocked scheme/host
        except Exception as exc:  # noqa: BLE001
            raise AssertionError(
                f"validate_fn raised unexpected {type(exc).__name__} for {url!r}: {exc}"
            ) from exc
        else:
            # If it didn't raise, the URL must be http/https with a non-blocked host.
            assert scheme in {"http", "https"}, f"non-http scheme {scheme!r} not blocked"
            assert host != "metadata.google.internal", "metadata host not blocked"

    _test.__name__ = "test_input_validation_property"
    return _test


# ---------------------------------------------------------------------------
# SP-3 — Data integrity
# ---------------------------------------------------------------------------

def make_data_integrity_property(sign_fn, verify_fn, *, max_examples: int = 200):
    """Return a Hypothesis test for sign/verify round-trip integrity.

    ``sign_fn(entry: dict) -> signed: dict``
    ``verify_fn(signed: dict) -> bool``

    Property: verify(sign(entry)) is True; any mutation of the signed record fails.
    """

    @settings(max_examples=max_examples, deadline=None)
    @given(entry=st.dictionaries(_DICT_KEYS, _DICT_VALS, max_size=5))
    def _test(entry):
        signed = sign_fn(entry)
        assert verify_fn(signed) is True, "verify(sign(entry)) must be True"
        # Tamper: mutate the payload if present, else mutate any value.
        tampered = dict(signed)
        if "payload" in tampered:
            tampered["payload"] = dict(entry, _tampered="1")
        elif tampered:
            first_key = next(iter(tampered))
            tampered[first_key] = str(tampered[first_key]) + "_tampered"
        assert verify_fn(tampered) is False, "verify(tampered) must be False"

    _test.__name__ = "test_data_integrity_property"
    return _test


# ---------------------------------------------------------------------------
# SP-4 — Corpus integrity
# ---------------------------------------------------------------------------

def make_corpus_integrity_property(verify_sha_fn, *, max_examples: int = 300):
    """Return a Hypothesis test for corpus SHA gate.

    ``verify_sha_fn(pinned: str, actual: str) -> bool``

    Property: pinned ≠ actual → False (fail closed); pinned == actual → True.
    """

    @settings(max_examples=max_examples)
    @given(pinned=_SHA, actual=_SHA)
    def _test(pinned, actual):
        result = verify_sha_fn(pinned=pinned, actual=actual)
        assert result == (pinned == actual), (
            f"SHA gate wrong: pinned={pinned[:8]}…, actual={actual[:8]}…, "
            f"result={result!r}"
        )

    _test.__name__ = "test_corpus_integrity_property"
    return _test


# ---------------------------------------------------------------------------
# SP-5 — Session / token permissions
# ---------------------------------------------------------------------------

def make_session_property(token_fn, *, max_examples: int = 50):
    """Return a Hypothesis test for token file permissions.

    ``token_fn(tmp_path: Path) -> Path``
    must write the token file with mode 0600 at creation.

    Property: ∀ tmp_path → mode(token_fn(tmp_path)) == 0o600.
    """
    import os
    import stat

    @settings(max_examples=max_examples)
    @given(_=st.just(None))
    def _test(_, tmp_path):  # tmp_path supplied by pytest fixture
        token_path = token_fn(tmp_path)
        mode = stat.S_IMODE(os.stat(token_path).st_mode)
        assert mode == 0o600, f"token file mode {oct(mode)} != 0o600"

    _test.__name__ = "test_session_property"
    return _test
