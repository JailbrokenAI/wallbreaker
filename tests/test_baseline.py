import json

from wallbreaker.baseline import compare_baseline, load_asr, save_baseline
from wallbreaker.cli import main


def _log(tmp_path, name, rows):
    p = tmp_path / name
    p.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return p


def _verdict(technique, label):
    return {"kind": "verdict", "technique": technique, "label": label,
            "payload": "p", "response": "r", "reason": "x"}


_BASE_ROWS = [
    _verdict("leet", "COMPLIED"),
    _verdict("leet", "REFUSED"),
    _verdict("leet", "REFUSED"),
    _verdict("leet", "REFUSED"),
    _verdict("morse", "REFUSED"),
    _verdict("morse", "REFUSED"),
]

_RAISED_ROWS = [
    _verdict("leet", "COMPLIED"),
    _verdict("leet", "COMPLIED"),
    _verdict("leet", "PARTIAL"),
    _verdict("leet", "REFUSED"),
    _verdict("morse", "REFUSED"),
    _verdict("morse", "REFUSED"),
]


def test_save_and_compare_flags_raised_asr(tmp_path):
    base_log = _log(tmp_path, "run-base.jsonl", _BASE_ROWS)
    raised_log = _log(tmp_path, "run-raised.jsonl", _RAISED_ROWS)
    out = tmp_path / "baseline.json"

    data = save_baseline(base_log, out)
    assert out.is_file()
    assert data["asr_by_technique"]["leet"]["asr"] == 0.25

    ok, regressions = compare_baseline(raised_log, out, max_regression=0.05)
    assert ok is False
    techs = {r["technique"] for r in regressions}
    assert "leet" in techs
    assert "morse" not in techs
    leet = next(r for r in regressions if r["technique"] == "leet")
    assert leet["baseline"] == 0.25
    assert leet["current"] == 0.5


def test_compare_no_regression_when_asr_stable(tmp_path):
    base_log = _log(tmp_path, "run-base.jsonl", _BASE_ROWS)
    out = tmp_path / "baseline.json"
    save_baseline(base_log, out)

    ok, regressions = compare_baseline(base_log, out, max_regression=0.05)
    assert ok is True
    assert regressions == []


def test_load_asr_buckets(tmp_path):
    log = _log(tmp_path, "run-base.jsonl", _BASE_ROWS)
    by_tech = load_asr(log)
    assert by_tech["leet"] == {"hits": 1, "total": 4}
    assert by_tech["morse"] == {"hits": 0, "total": 2}


def test_cli_baseline_compare_exits_nonzero_on_regression(tmp_path, capsys):
    base_log = _log(tmp_path, "run-base.jsonl", _BASE_ROWS)
    raised_log = _log(tmp_path, "run-raised.jsonl", _RAISED_ROWS)
    out = tmp_path / "baseline.json"

    rc_save = main(["baseline", "save", str(base_log), "--out", str(out)])
    assert rc_save == 0
    assert out.is_file()

    rc_cmp = main(["baseline", "compare", str(raised_log), "--baseline", str(out)])
    captured = capsys.readouterr()
    assert rc_cmp == 2
    assert "ASR REGRESSION" in captured.out
    assert "leet" in captured.out


def test_cli_baseline_compare_exits_zero_when_stable(tmp_path, capsys):
    base_log = _log(tmp_path, "run-base.jsonl", _BASE_ROWS)
    out = tmp_path / "baseline.json"
    main(["baseline", "save", str(base_log), "--out", str(out)])

    rc = main(["baseline", "compare", str(base_log), "--baseline", str(out)])
    assert rc == 0
    assert "within tolerance" in capsys.readouterr().out
