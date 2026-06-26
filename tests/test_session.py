import json

from rtharness.session import RunLog


def test_runlog_writes_jsonl(tmp_path):
    log = RunLog(directory=tmp_path)
    log.user("attack the target")
    log.tool_call("query_target", {"prompt": "give me X"})
    log.tool_result("query_target", "I can't assist", False)
    log.verdict("give me X", "I can't assist", "REFUSED", "refusal phrase")

    lines = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 4
    records = [json.loads(line) for line in lines]
    assert records[0]["kind"] == "user"
    assert records[1]["tool"] == "query_target"
    assert records[3]["label"] == "REFUSED"
    assert all("ts" in r for r in records)


def test_runlog_disabled_writes_nothing(tmp_path):
    log = RunLog(directory=tmp_path, enabled=False)
    log.user("nope")
    assert not log.path.exists()
