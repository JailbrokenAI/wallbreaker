"""Regression tests: the `corpus verify` CLI routing must stay reachable.

The dispatch was born in 53c9ca2 (roadmap-implementation TG3) and silently
lost when the PR #21 and PR #24 lines merged in da21689 — _run_corpus_verify
survived as dead code while nothing failed. These tests pin the routing so a
future merge cannot strand the command again.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import wallbreaker.cli as cli
from wallbreaker.cli import SUBCOMMANDS, _run_corpus_verify, build_sub_parser


def test_corpus_in_subcommands():
    assert "corpus" in SUBCOMMANDS


def test_corpus_verify_parses():
    args = build_sub_parser().parse_args(["corpus", "verify"])
    assert args.command == "corpus"
    assert args.corpus_action == "verify"
    assert args.update is False


def test_corpus_verify_parses_update_and_lock():
    args = build_sub_parser().parse_args(
        ["corpus", "verify", "--update", "--lock", "/tmp/other.lock.toml"]
    )
    assert args.update is True
    assert args.lock == "/tmp/other.lock.toml"


def test_parsel_verify_alias_parses():
    args = build_sub_parser().parse_args(["parsel", "verify"])
    assert args.command == "parsel"
    assert args.parsel_action == "verify"


def test_main_routes_corpus_verify(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lock = tmp_path / "library.lock.toml"
    lock.write_text("", encoding="utf-8")
    called = {}

    def fake_verify(args):
        called["lock"] = args.lock
        return 7

    monkeypatch.setattr(cli, "_run_corpus_verify", fake_verify)
    rc = cli.main(["corpus", "verify", "--lock", str(lock)])
    assert rc == 7
    assert called["lock"] == str(lock)


def test_main_routes_parsel_verify_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    called = {}

    def fake_verify(args):
        called["via"] = "parsel"
        return 0

    monkeypatch.setattr(cli, "_run_corpus_verify", fake_verify)
    rc = cli.main(["parsel", "verify"])
    assert rc == 0
    assert called["via"] == "parsel"


def test_main_routes_parsel_update_to_parsel_lib(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The verify alias must not swallow the real parsel actions."""
    monkeypatch.setattr(
        "wallbreaker.tools.parsel_lib.run_parsel_cli", lambda args: 0
    )
    rc = cli.main(["parsel", "list"])
    assert rc == 0
