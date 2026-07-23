"""Signed, append-only findings log (TG7 — Trust Frontier, item H).

Each entry is signed with Ed25519 (via the `cryptography` package) so the log is
tamper-evident: any mutation of a stored record is detected at load time.

Security properties enforced:
- R-H1: verify(sign(entry)) == True; any payload mutation → False.
- R-H2: private key is NEVER written to disk — only the public key is embedded in
  the signed record (so verifiers are self-contained without the private key).
- 7.7: all writes use atomic_write from _fsutil (temp-file + fsync + os.replace).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from ._fsutil import atomic_write


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def generate_keypair() -> tuple[bytes, bytes]:
    """Return (private_key_bytes, public_key_bytes) as raw 32-byte sequences."""
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return private_bytes, public_bytes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _canonical_json(entry: dict) -> bytes:
    """Stable, deterministic serialisation used as the signature message."""
    return json.dumps(entry, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _load_private_key(private_key_bytes: bytes) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(private_key_bytes)


def _load_public_key(public_key_bytes: bytes) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(public_key_bytes)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sign_entry(entry: dict, private_key_bytes: Optional[bytes] = None) -> dict:
    """Sign a findings entry.

    Returns a new dict with:
      - "payload": the original entry (unchanged copy — input is not mutated)
      - "sig": hex-encoded Ed25519 signature over the canonical JSON of payload
      - "pubkey": hex-encoded public key (verifier is self-contained; no private key)

    ``private_key_bytes`` is optional: if *None*, an ephemeral key is generated for
    this call (useful for property-based tests that only care about tamper detection).
    The private key is NEVER included in the returned dict (R-H2).
    """
    if private_key_bytes is None:
        private_key_bytes, _ = generate_keypair()

    private_key = _load_private_key(private_key_bytes)
    public_bytes = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    canonical = _canonical_json(entry)
    signature = private_key.sign(canonical)

    return {
        "payload": dict(entry),   # shallow copy — never mutate caller's dict
        "sig": signature.hex(),
        "pubkey": public_bytes.hex(),
    }


def verify_entry(signed: dict) -> bool:
    """Verify a signed entry.

    Returns True if the signature is valid, False on any error (missing fields,
    bad encoding, wrong key, corrupted signature, tampered payload, …).
    Never raises.
    """
    try:
        payload = signed["payload"]
        sig_bytes = bytes.fromhex(signed["sig"])
        pubkey_bytes = bytes.fromhex(signed["pubkey"])

        public_key = _load_public_key(pubkey_bytes)
        canonical = _canonical_json(payload)
        public_key.verify(sig_bytes, canonical)
        return True
    except (KeyError, ValueError, InvalidSignature, Exception):  # noqa: BLE001
        return False


def append_finding(log_path: Path | str, entry: dict, private_key_bytes: bytes) -> None:
    """Append a signed entry to the findings log (JSONL — one JSON object per line).

    Uses atomic_write so readers never see a truncated or partially-written file
    (R-H1 / 7.7).  The log is append-only by convention; existing lines are never
    mutated.
    """
    log_path = Path(log_path)

    existing = ""
    if log_path.exists():
        existing = log_path.read_text(encoding='utf-8')

    signed = sign_entry(entry, private_key_bytes)
    new_line = json.dumps(signed, sort_keys=True, separators=(',', ':')) + "\n"

    atomic_write(log_path, existing + new_line)


def load_findings(log_path: Path | str) -> list[dict]:
    """Load and verify every entry in the log.

    Returns a list of the verified *payload* dicts (inner content, not the signed
    wrappers).  Raises ValueError on the first entry that fails signature
    verification so callers get a clear tamper signal rather than silently dropping
    bad entries.
    """
    log_path = Path(log_path)

    if not log_path.exists():
        return []

    content = log_path.read_text(encoding='utf-8')
    results: list[dict] = []

    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        try:
            signed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON at line {lineno}: {exc}") from exc

        if not verify_entry(signed):
            raise ValueError(
                f"Signature verification failed at line {lineno} — log may be tampered"
            )

        results.append(signed["payload"])

    return results
