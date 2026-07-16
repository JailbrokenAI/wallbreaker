import asyncio
import json

from wallbreaker.config import Config, Endpoint
from wallbreaker.report import build_report
from wallbreaker.session import RunLog


def test_runlog_verdict_records_technique(tmp_path):
    rl = RunLog(directory=str(tmp_path))
    rl.verdict("p", "r", "COMPLIED", "reason", technique="prefill")
    rec = json.loads(rl.path.read_text(encoding="utf-8").strip())
    assert rec["technique"] == "prefill"


def test_runlog_verdict_defaults_manual(tmp_path):
    rl = RunLog(directory=str(tmp_path))
    rl.verdict("p", "r", "REFUSED", "reason")
    rec = json.loads(rl.path.read_text(encoding="utf-8").strip())
    assert rec["technique"] == "manual"


def test_report_includes_technique_table(tmp_path):
    log = tmp_path / "run.jsonl"
    rows = [
        {"kind": "verdict", "payload": "a", "label": "COMPLIED", "reason": "x", "technique": "prefill"},
        {"kind": "verdict", "payload": "b", "label": "REFUSED", "reason": "y", "technique": "prefill"},
        {"kind": "verdict", "payload": "c", "label": "COMPLIED", "reason": "z", "technique": "template"},
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    md = build_report(log)
    assert "ASR by technique" in md
    assert "| prefill | 1 | 0 | 2 | 50% | 50% |" in md
    assert "| template | 1 | 0 | 1 | 100% | 100% |" in md


def _build_app(tmp_path):
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": True})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_record_verdict_threads_technique(tmp_path):
    app = _build_app(tmp_path)
    app._record_verdict("payload", "reply", "COMPLIED", "reason", "many_shot")
    rec = json.loads(app.runlog.path.read_text(encoding="utf-8").strip())
    assert rec["technique"] == "many_shot"


def test_stats_shows_technique_breakdown(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.runlog.path.write_text(
            "\n".join(json.dumps(r) for r in [
                {"kind": "verdict", "payload": "a", "label": "COMPLIED", "reason": "x", "technique": "prefill"},
                {"kind": "verdict", "payload": "b", "label": "REFUSED", "reason": "y", "technique": "query_target"},
            ]),
            encoding="utf-8",
        )
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app._cmd_stats()
            await pilot.pause()
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())
