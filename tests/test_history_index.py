import json
import sqlite3

import pytest

from wallbreaker.history_index import HistoryIndex, REDACTED


def _write_run(directory, name, records, extra_lines=()):
    directory.mkdir(exist_ok=True)
    path = directory / f"run-{name}.jsonl"
    lines = [json.dumps(record) for record in records]
    lines.extend(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_rebuild_indexes_events_and_run_summaries(tmp_path):
    sessions = tmp_path / "sessions"
    _write_run(sessions, "alpha", [
        {"ts": "2026-01-01T00:00:00", "kind": "objective", "seq": 1, "text": "probe alpha"},
        {
            "ts": "2026-01-01T00:00:01", "kind": "verdict", "seq": 2,
            "actor": "judge", "technique": "crescendo", "label": "COMPLIED",
            "duration_ms": 12.5, "usage": {"input_tokens": 10, "output_tokens": 4},
            "cost_usd": 0.003, "execution_id": "exec-1", "round": 2,
            "inference_id": "inf-1", "tool_use_id": "tool-1", "response": "evidence needle",
        },
    ])

    with HistoryIndex(tmp_path / "history.sqlite") as index:
        status = index.rebuild(sessions)
        assert status["run_count"] == 1
        assert status["event_count"] == 2
        result = index.query_events(text="needle")
        assert result["total"] == 1
        event = result["items"][0]
        assert event["run_name"] == "run-alpha"
        assert event["round_id"] == "2"
        assert event["input_tokens"] == 10
        assert event["output_tokens"] == 4
        summary = index.run_summaries()["items"][0]
        assert summary["event_count"] == 2
        assert summary["verdicts"] == {"COMPLIED": 1}


@pytest.mark.parametrize("use_fts", [True, False])
def test_free_text_search_uses_fts_or_fallback(tmp_path, use_fts):
    sessions = tmp_path / "sessions"
    _write_run(sessions, "search", [
        {"kind": "assistant", "text": "distinctive observatory phrase"},
        {"kind": "assistant", "text": "something else"},
    ])
    try:
        index = HistoryIndex(tmp_path / f"search-{use_fts}.sqlite", use_fts=use_fts)
    except sqlite3.OperationalError:  # pragma: no cover - unusual SQLite builds
        pytest.skip("SQLite was built without FTS5")
    with index:
        index.rebuild(sessions)
        result = index.query_events("observatory")
        assert result["total"] == 1
        assert "distinctive observatory" in result["items"][0]["searchable_text"]


def test_structured_facets_and_pagination(tmp_path):
    sessions = tmp_path / "sessions"
    _write_run(sessions, "facets", [
        {"seq": 1, "kind": "verdict", "actor": "judge", "technique": "pair", "label": "REFUSED"},
        {"seq": 2, "kind": "verdict", "actor": "judge", "technique": "pair", "label": "COMPLIED"},
        {"seq": 3, "kind": "tool_call", "actor": "brain", "tool_use_id": "call-3"},
    ])
    with HistoryIndex(tmp_path / "facets.sqlite") as index:
        index.rebuild(sessions)
        filtered = index.query_events(
            facets={"event_type": "verdict", "actor": "judge", "technique": "pair"},
            verdict="COMPLIED", limit=1, offset=0,
        )
        assert filtered["total"] == 1
        assert filtered["items"][0]["sequence"] == 2
        assert index.query_events(event_type="verdict", limit=1, offset=1)["total"] == 2


def test_recursive_redaction_preserves_numeric_token_counts(tmp_path):
    sessions = tmp_path / "sessions"
    _write_run(sessions, "secret", [{
        "kind": "inference", "api_key": "key-visible-in-source",
        "request": {
            "headers": {"Authorization": "Bearer hidden", "Cookie": "sid=hidden"},
            "password": "hidden", "access_token": "hidden-token",
            "usage": {"input_tokens": 17, "output_tokens": 9, "max_tokens": 100},
        },
    }])
    with HistoryIndex(tmp_path / "secret.sqlite") as index:
        index.rebuild(sessions)
        event = index.query_events()["items"][0]
        structured = json.loads(event["structured_json"])
        assert structured["api_key"] == REDACTED
        assert structured["request"]["headers"]["Authorization"] == REDACTED
        assert structured["request"]["headers"]["Cookie"] == REDACTED
        assert structured["request"]["access_token"] == REDACTED
        assert structured["request"]["usage"] == {
            "input_tokens": 17, "max_tokens": 100, "output_tokens": 9,
        }
        assert "key-visible-in-source" not in event["searchable_text"]
        assert index.query_events("key-visible-in-source")["total"] == 0


def test_malformed_legacy_lines_are_counted_and_skipped(tmp_path):
    sessions = tmp_path / "sessions"
    _write_run(
        sessions, "legacy",
        [{"timestamp": "old-time", "type": "progress", "sequence": 7, "text": "valid"}],
        extra_lines=("{not json", "[1, 2, 3]", ""),
    )
    with HistoryIndex(tmp_path / "legacy.sqlite") as index:
        status = index.rebuild(sessions)
        assert status["event_count"] == 1
        assert status["malformed_lines"] == 2
        event = index.query_events()["items"][0]
        assert (event["event_type"], event["sequence"], event["timestamp"]) == (
            "progress", 7, "old-time",
        )


def test_rebuild_and_incremental_upsert_are_idempotent(tmp_path):
    sessions = tmp_path / "sessions"
    path = _write_run(sessions, "incremental", [{"seq": 1, "kind": "user", "text": "one"}])
    with HistoryIndex(tmp_path / "incremental.sqlite") as index:
        index.rebuild(sessions)
        index.rebuild(sessions)
        assert index.status()["event_count"] == 1
        assert index.index_file(path)["skipped"] is True

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"seq": 2, "kind": "assistant", "text": "two"}) + "\n")
        changed = index.index_file(path)
        assert changed["skipped"] is False
        assert changed["event_count"] == 2
        assert index.index_file(path)["skipped"] is True
        assert index.query_events(run_name="run-incremental")["total"] == 2

        index.upsert_event(
            "run-incremental", {"seq": 2, "kind": "assistant", "text": "updated"}, source_line=2
        )
        assert index.query_events("updated")["total"] == 1
        assert index.status()["event_count"] == 2
