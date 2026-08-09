"""Task Group 3 (Supply-Chain Corpus Pinning) focused tests — TG3.4 and TG3.5."""
from __future__ import annotations

import pytest

from wallbreaker.tools.parsel_engine import load_corpus_with_pin_check, verify_corpus_sha


# ---------------------------------------------------------------------------
# Task 3.4 — happy path: matching SHA loads
# ---------------------------------------------------------------------------

def test_verify_corpus_sha_match():
    assert verify_corpus_sha(pinned="abc123", actual="abc123") is True


def test_verify_corpus_sha_match_40char():
    sha = "a" * 40
    assert verify_corpus_sha(pinned=sha, actual=sha) is True


# ---------------------------------------------------------------------------
# Task 3.5 — drift path: mismatched SHA refuses
# ---------------------------------------------------------------------------

def test_verify_corpus_sha_mismatch():
    assert verify_corpus_sha(pinned="abc123", actual="def456") is False


def test_verify_corpus_sha_unresolved():
    assert verify_corpus_sha(pinned="UNRESOLVED", actual="abc123") is False


def test_load_corpus_unresolved_fails(tmp_path):
    lock = tmp_path / "library.lock.toml"
    lock.write_text('[corpus.TEST]\nrepo = "x"\nsha = "UNRESOLVED"\nfetched = "2026-07-23"\n')
    with pytest.raises(RuntimeError, match="not yet pinned"):
        load_corpus_with_pin_check("TEST", lock_path=lock)


def test_load_corpus_unknown_fails(tmp_path):
    lock = tmp_path / "library.lock.toml"
    lock.write_text('[corpus.OTHER]\nrepo = "x"\nsha = "abc"\nfetched = "2026-07-23"\n')
    with pytest.raises(RuntimeError, match="not in library.lock.toml"):
        load_corpus_with_pin_check("MISSING", lock_path=lock)


def test_load_corpus_measures_local_head_and_rejects_drift(tmp_path):
    import subprocess
    repo = tmp_path / "corpus"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "seed.txt").write_text("seed")
    subprocess.run(["git", "-C", str(repo), "add", "seed.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "seed"], check=True)
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()

    lock = tmp_path / "library.lock.toml"
    lock.write_text(f'[corpus.TEST]\nrepo = "x"\nsha = "{head}"\n')
    assert load_corpus_with_pin_check("TEST", lock_path=lock, corpus_path=repo) == head

    lock.write_text(f'[corpus.TEST]\nrepo = "x"\nsha = "{"0" * 40}"\n')
    with pytest.raises(RuntimeError, match="integrity mismatch"):
        load_corpus_with_pin_check("TEST", lock_path=lock, corpus_path=repo)
