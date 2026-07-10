import json

from wallbreaker.session import RunLog


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


def test_runlog_writes_pending_run_metadata_on_first_event(tmp_path):
    log = RunLog(directory=tmp_path)
    log.set_run_meta(models={
        "attacker": "attacker-model",
        "target": "target-model",
        "judge": "judge-model",
    })
    assert not log.path.exists()

    log.event("objective", text="break it")

    records = [
        json.loads(line)
        for line in log.path.read_text(encoding="utf-8").strip().splitlines()
    ]
    assert records[0]["kind"] == "run_meta"
    assert records[0]["models"]["attacker"] == "attacker-model"
    assert records[0]["models"]["target"] == "target-model"
    assert records[0]["models"]["judge"] == "judge-model"
    assert records[1]["kind"] == "objective"


def test_session_save_load_roundtrip(tmp_path):
    from wallbreaker.agent.messages import (
        Message,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        user,
    )
    from wallbreaker.session import load_session, save_session

    history = [
        user("attack the target"),
        Message("assistant", [TextBlock("ok"), ToolUseBlock("c1", "query_target", {"prompt": "x"})]),
        Message("user", [ToolResultBlock("c1", "refused", False)]),
    ]
    path = tmp_path / "s.json"
    save_session(path, history, {"objective": "break it", "asr_total": 1})

    loaded, meta = load_session(path)
    assert meta["objective"] == "break it"
    assert len(loaded) == 3
    assert loaded[1].tool_uses()[0].name == "query_target"
    assert isinstance(loaded[2].content[0], ToolResultBlock)
    assert loaded[2].content[0].content == "refused"
