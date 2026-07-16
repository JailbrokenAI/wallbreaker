import asyncio
import json

from wallbreaker.config import Config, Endpoint
from wallbreaker.report import (
    asr_by_technique,
    build_findings_export,
    build_html_report,
)


_ROWS = [
    {"kind": "verdict", "payload": "a", "label": "COMPLIED", "reason": "x", "technique": "prefill", "ts": "t1", "response": "r"},
    {"kind": "verdict", "payload": "b", "label": "REFUSED", "reason": "y", "technique": "prefill"},
    {"kind": "verdict", "payload": "c", "label": "PARTIAL", "reason": "z", "technique": "many_shot", "ts": "t3", "response": "r"},
]


def _write(tmp_path):
    log = tmp_path / "run.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in _ROWS), encoding="utf-8")
    return log


def test_asr_by_technique():
    out = asr_by_technique([r for r in _ROWS])
    assert out["prefill"]["strict_hits"] == 1
    assert out["prefill"]["partial_hits"] == 0
    assert out["prefill"]["total"] == 2
    assert out["many_shot"]["strict_hits"] == 0
    assert out["many_shot"]["partial_hits"] == 1
    assert out["many_shot"]["total"] == 1


def test_export_carries_technique(tmp_path):
    data = build_findings_export(_write(tmp_path))
    assert data["asr_by_technique"]["prefill"]["total"] == 2
    techniques = {f["technique"] for f in data["findings"]}
    assert techniques == {"prefill", "many_shot"}  # only bypasses (COMPLIED/PARTIAL)


def test_html_report_has_technique_column(tmp_path):
    html = build_html_report(_write(tmp_path))
    assert "<th>technique</th>" in html
    assert ">prefill<" in html


def _build_app(tmp_path):
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.session import RunLog
    from wallbreaker.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_tui_export_includes_technique(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.runlog.path.write_text("\n".join(json.dumps(r) for r in _ROWS), encoding="utf-8")
        out = tmp_path / "findings.json"
        async with app.run_test() as pilot:
            app._cmd_export([str(out)])
            await pilot.pause()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert all("technique" in f for f in data["findings"])

    asyncio.run(run())


def test_repro_pack_shows_technique(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        app.runlog.path.write_text(json.dumps(_ROWS[0]), encoding="utf-8")
        captured = {}
        app.copy_to_clipboard = lambda t: captured.__setitem__("t", t)
        async with app.run_test() as pilot:
            app._cmd_repro([])
            await pilot.pause()
        assert "technique    : prefill" in captured["t"]

    asyncio.run(run())
