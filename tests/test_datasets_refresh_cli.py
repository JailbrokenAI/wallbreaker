"""datasets status/refresh API + CLI wiring (offline)."""

from __future__ import annotations

import asyncio

from wallbreaker import datasets
from wallbreaker.cli import build_sub_parser, main


def test_status_includes_sorry_and_xstest():
    rows = {r["source"]: r for r in datasets.status()}
    assert "sorrybench" in rows
    assert "xstest" in rows
    assert rows["xstest"]["has_benign"] is True
    assert rows["sorrybench"]["rows"] >= 40


def test_refresh_offline_keeps_bundled(monkeypatch):
    # Force download failures; bundled samples must still leave status healthy.
    from wallbreaker.datasets import _common

    def boom(url, path, label="dataset"):
        return f"{label} download failed: offline-test"

    monkeypatch.setattr(_common, "download", boom)
    results = asyncio.run(datasets.refresh("xstest", force=True))
    # May report fail for remote, but load still works via bundle
    assert datasets.load("xstest")
    assert datasets.load("sorrybench")
    assert "xstest" in results


def test_cli_datasets_list(capsys):
    rc = main(["datasets", "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sorrybench" in out
    assert "xstest" in out


def test_cli_parser_has_datasets():
    # build_sub_parser is used for subcommands
    from wallbreaker import cli as cli_mod

    p = cli_mod.build_sub_parser()
    # ensure datasets is a known subcommand choice via help or parse
    ns = p.parse_args(["datasets", "list"])
    assert ns.command == "datasets"
    assert ns.datasets_action == "list"


def test_campaign_bandit_default_true():
    text = open("wallbreaker/tools/campaign.py", encoding="utf-8").read()
    assert 'args.get("bandit", True)' in text
