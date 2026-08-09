"""Disposable SQLite search index for canonical Wallbreaker JSONL run logs.

The JSONL files remain the source of truth.  This module deliberately owns no
history: its database can be deleted and rebuilt from ``sessions/run-*.jsonl``
at any time.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = 1
REDACTED = "[REDACTED]"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalise_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")


def _is_token_count(key: str, value: object) -> bool:
    """Distinguish numeric usage/budget fields from authentication tokens."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    return (
        key == "tokens"
        or key.endswith("_tokens")
        or key.endswith("_token_count")
        or key in {"token_count", "max_tokens", "budget_tokens"}
    )


def _is_sensitive_key(key: object, value: object) -> bool:
    normalised = _normalise_key(key)
    if "token" in normalised and not _is_token_count(normalised, value):
        return True
    return any(
        marker in normalised
        for marker in ("api_key", "authorization", "secret", "password", "cookie")
    )


def redact(value: Any) -> Any:
    """Return a recursively redacted, JSON-compatible copy of *value*."""
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key, item) else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _at(record: Mapping[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        value: Any = record
        for part in path:
            if not isinstance(value, Mapping) or part not in value:
                break
            value = value[part]
        else:
            if value not in (None, ""):
                return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _numeric_values(value: Any, names: set[str]) -> Iterable[float]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _normalise_key(key) in names:
                number = _number(item)
                if number is not None:
                    yield number
            if isinstance(item, (Mapping, list, tuple)):
                yield from _numeric_values(item, names)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _numeric_values(item, names)


def _usage_value(record: Mapping[str, Any], names: set[str]) -> float | None:
    values = list(_numeric_values(record, names))
    # Stream usage records may repeat cumulative counts.  The maximum avoids
    # double-counting while still handling both compact and legacy schemas.
    return max(values) if values else None


def _searchable_values(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _searchable_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _searchable_values(item)
    elif value is not None and value != REDACTED:
        yield str(value)


def _event_fields(record: Mapping[str, Any], source_line: int) -> dict[str, Any]:
    event_type = str(_at(record, ("kind",), ("event_type",), ("type",)) or "unknown")
    actor = _at(
        record,
        ("actor",),
        ("source",),
        ("role",),
        ("request", "endpoint", "name"),
        ("endpoint", "name"),
        ("event", "actor"),
    )
    if actor is None and event_type in {"user", "assistant", "target", "judge", "attack", "art"}:
        actor = event_type

    redacted = redact(record)
    structured_json = json.dumps(redacted, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "source_line": source_line,
        "sequence": _integer(_at(record, ("seq",), ("sequence",))) or source_line,
        "timestamp": str(_at(record, ("ts",), ("timestamp",), ("created_at",), ("time",)) or ""),
        "event_type": event_type,
        "actor": str(actor or ""),
        "technique": str(_at(record, ("technique",), ("strategy",), ("preset",), ("metadata", "technique")) or ""),
        "verdict": str(_at(record, ("verdict",), ("label",), ("result", "label"), ("event", "verdict")) or ""),
        "latency_ms": _usage_value(record, {"latency_ms", "duration_ms", "elapsed_ms"}),
        "input_tokens": _integer(_usage_value(record, {"input_tokens", "prompt_tokens"})),
        "output_tokens": _integer(_usage_value(record, {"output_tokens", "completion_tokens"})),
        "cost": _usage_value(record, {"cost", "cost_usd", "total_cost", "total_cost_usd"}),
        "execution_id": str(_at(record, ("execution_id",), ("job_id",), ("correlation", "execution_id")) or ""),
        "round_id": str(_at(record, ("round_id",), ("round",), ("correlation", "round_id")) or ""),
        "inference_id": str(_at(record, ("inference_id",), ("correlation", "inference_id")) or ""),
        "tool_id": str(_at(
            record,
            ("tool_id",),
            ("tool_use_id",),
            ("tool_call_id",),
            ("call_id",),
            ("correlation", "tool_id"),
        ) or ""),
        "searchable_text": "\n".join(_searchable_values(redacted)),
        "structured_json": structured_json,
    }


class HistoryIndex:
    """Rebuildable, queryable index over Wallbreaker run JSONL files."""

    def __init__(self, database: str | Path, *, use_fts: bool | None = None):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI may construct the app and service sync endpoints on different
        # worker threads. Access remains serialized by the API adapter, while
        # disabling the sqlite creator-thread guard keeps lifecycle shutdown safe.
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._create_schema()
        self.fts_enabled = self._configure_fts(use_fts)

    def __enter__(self) -> "HistoryIndex":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._connection.close()

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                run_name TEXT PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_size INTEGER NOT NULL DEFAULT 0,
                source_mtime_ns INTEGER NOT NULL DEFAULT 0,
                event_count INTEGER NOT NULL DEFAULT 0,
                malformed_lines INTEGER NOT NULL DEFAULT 0,
                first_timestamp TEXT NOT NULL DEFAULT '',
                last_timestamp TEXT NOT NULL DEFAULT '',
                total_input_tokens INTEGER NOT NULL DEFAULT 0,
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                total_cost REAL NOT NULL DEFAULT 0,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY,
                run_name TEXT NOT NULL REFERENCES runs(run_name) ON DELETE CASCADE,
                source_line INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                timestamp TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT 'unknown',
                actor TEXT NOT NULL DEFAULT '',
                technique TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL DEFAULT '',
                latency_ms REAL,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost REAL,
                execution_id TEXT NOT NULL DEFAULT '',
                round_id TEXT NOT NULL DEFAULT '',
                inference_id TEXT NOT NULL DEFAULT '',
                tool_id TEXT NOT NULL DEFAULT '',
                searchable_text TEXT NOT NULL DEFAULT '',
                structured_json TEXT NOT NULL,
                UNIQUE(run_name, source_line)
            );
            CREATE INDEX IF NOT EXISTS events_run_sequence ON events(run_name, sequence);
            CREATE INDEX IF NOT EXISTS events_timestamp ON events(timestamp);
            CREATE INDEX IF NOT EXISTS events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS events_actor ON events(actor);
            CREATE INDEX IF NOT EXISTS events_technique ON events(technique);
            CREATE INDEX IF NOT EXISTS events_verdict ON events(verdict);
            CREATE INDEX IF NOT EXISTS events_execution ON events(execution_id);
            CREATE INDEX IF NOT EXISTS events_inference ON events(inference_id);
            """
        )
        self._connection.execute(
            "INSERT INTO metadata(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self._connection.commit()

    def _configure_fts(self, requested: bool | None) -> bool:
        if requested is False:
            return False
        try:
            self._connection.executescript(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
                    searchable_text, content='events', content_rowid='id'
                );
                CREATE TRIGGER IF NOT EXISTS events_fts_insert AFTER INSERT ON events BEGIN
                    INSERT INTO events_fts(rowid, searchable_text)
                    VALUES (new.id, new.searchable_text);
                END;
                CREATE TRIGGER IF NOT EXISTS events_fts_delete AFTER DELETE ON events BEGIN
                    INSERT INTO events_fts(events_fts, rowid, searchable_text)
                    VALUES ('delete', old.id, old.searchable_text);
                END;
                CREATE TRIGGER IF NOT EXISTS events_fts_update AFTER UPDATE ON events BEGIN
                    INSERT INTO events_fts(events_fts, rowid, searchable_text)
                    VALUES ('delete', old.id, old.searchable_text);
                    INSERT INTO events_fts(rowid, searchable_text)
                    VALUES (new.id, new.searchable_text);
                END;
                """
            )
            self._connection.execute("INSERT INTO events_fts(events_fts) VALUES('rebuild')")
            self._connection.commit()
            return True
        except sqlite3.OperationalError:
            self._connection.rollback()
            if requested is True:
                raise
            return False

    def rebuild(self, sessions: str | Path = "sessions") -> dict[str, Any]:
        """Discard indexed data and rebuild it from ``run-*.jsonl`` files."""
        directory = Path(sessions)
        with self._connection:
            self._connection.execute("DELETE FROM events")
            self._connection.execute("DELETE FROM runs")
            self._set_meta("source_directory", str(directory.resolve()))
            self._set_meta("last_rebuild_at", _utc_now())
        for path in sorted(directory.glob("run-*.jsonl")):
            if path.is_file():
                self.index_file(path, force=True)
        return self.status()

    def update(self, sessions: str | Path = "sessions") -> dict[str, Any]:
        """Incrementally index new or changed canonical run files."""
        directory = Path(sessions)
        changed = 0
        skipped = 0
        current_paths = {
            str(path.resolve()): path
            for path in sorted(directory.glob("run-*.jsonl"))
            if path.is_file()
        }
        # The database is disposable and must mirror the canonical directory.
        # Prune rows for logs that were archived or deleted between updates.
        indexed_paths = {
            row["run_name"]: row["source_path"]
            for row in self._connection.execute("SELECT run_name, source_path FROM runs")
        }
        removed = [
            run_name for run_name, source_path in indexed_paths.items()
            if source_path and source_path not in current_paths
        ]
        if removed:
            with self._connection:
                self._connection.executemany(
                    "DELETE FROM runs WHERE run_name = ?",
                    ((run_name,) for run_name in removed),
                )
        for path in current_paths.values():
            result = self.index_file(path)
            changed += int(not result["skipped"])
            skipped += int(result["skipped"])
        result = self.status()
        result.update({
            "changed_runs": changed,
            "skipped_runs": skipped,
            "removed_runs": len(removed),
        })
        return result

    def index_file(self, path: str | Path, *, force: bool = False) -> dict[str, Any]:
        """Upsert one run file, replacing only that run when its source changed."""
        source = Path(path)
        stat = source.stat()
        run_name = source.stem
        existing = self._connection.execute(
            "SELECT source_size, source_mtime_ns, event_count, malformed_lines "
            "FROM runs WHERE run_name = ?",
            (run_name,),
        ).fetchone()
        if (
            not force
            and existing is not None
            and existing["source_size"] == stat.st_size
            and existing["source_mtime_ns"] == stat.st_mtime_ns
        ):
            return {
                "run_name": run_name,
                "event_count": existing["event_count"],
                "malformed_lines": existing["malformed_lines"],
                "skipped": True,
            }

        records: list[tuple[int, Mapping[str, Any]]] = []
        malformed = 0
        with source.open("r", encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    malformed += 1
                    continue
                if not isinstance(record, Mapping):
                    malformed += 1
                    continue
                records.append((line_number, record))

        indexed_at = _utc_now()
        with self._connection:
            self._connection.execute("DELETE FROM runs WHERE run_name = ?", (run_name,))
            self._connection.execute(
                """INSERT INTO runs(
                    run_name, source_path, source_size, source_mtime_ns,
                    malformed_lines, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_name, str(source.resolve()), stat.st_size, stat.st_mtime_ns, malformed, indexed_at),
            )
            for line_number, record in records:
                self._insert_event(run_name, record, line_number)
            self._refresh_run(run_name, len(records), malformed, indexed_at)

        return {
            "run_name": run_name,
            "event_count": len(records),
            "malformed_lines": malformed,
            "skipped": False,
        }

    # Friendly aliases for callers that describe this operation as an upsert.
    upsert_run = index_file
    incremental_update = update

    def upsert_event(
        self,
        run_name: str,
        record: Mapping[str, Any],
        *,
        source_line: int | None = None,
        source_path: str = "",
    ) -> dict[str, Any]:
        """Incrementally upsert an already-parsed event by run and source line."""
        if not isinstance(record, Mapping):
            raise TypeError("record must be a mapping")
        line = source_line or _integer(record.get("source_line")) or _integer(record.get("seq"))
        if line is None:
            row = self._connection.execute(
                "SELECT COALESCE(MAX(source_line), 0) + 1 FROM events WHERE run_name = ?",
                (run_name,),
            ).fetchone()
            line = int(row[0])
        now = _utc_now()
        with self._connection:
            self._connection.execute(
                """INSERT INTO runs(run_name, source_path, indexed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(run_name) DO UPDATE SET indexed_at=excluded.indexed_at""",
                (run_name, source_path, now),
            )
            self._insert_event(run_name, record, line)
            count = self._connection.execute(
                "SELECT COUNT(*) FROM events WHERE run_name = ?", (run_name,)
            ).fetchone()[0]
            malformed = self._connection.execute(
                "SELECT malformed_lines FROM runs WHERE run_name = ?", (run_name,)
            ).fetchone()[0]
            self._refresh_run(run_name, count, malformed, now)
        return dict(self._connection.execute(
            "SELECT * FROM events WHERE run_name = ? AND source_line = ?", (run_name, line)
        ).fetchone())

    def _insert_event(self, run_name: str, record: Mapping[str, Any], source_line: int) -> None:
        fields = _event_fields(record, source_line)
        columns = ", ".join(fields)
        placeholders = ", ".join("?" for _ in fields)
        updates = ", ".join(
            f"{column}=excluded.{column}" for column in fields if column != "source_line"
        )
        self._connection.execute(
            f"""INSERT INTO events(run_name, {columns})
            VALUES (?, {placeholders})
            ON CONFLICT(run_name, source_line) DO UPDATE SET {updates}""",
            (run_name, *fields.values()),
        )

    def _refresh_run(self, run_name: str, count: int, malformed: int, indexed_at: str) -> None:
        aggregate = self._connection.execute(
            """SELECT
                COALESCE(MIN(NULLIF(timestamp, '')), ''),
                COALESCE(MAX(timestamp), ''),
                COALESCE(SUM(input_tokens), 0),
                COALESCE(SUM(output_tokens), 0),
                COALESCE(SUM(cost), 0)
            FROM events WHERE run_name = ?""",
            (run_name,),
        ).fetchone()
        self._connection.execute(
            """UPDATE runs SET
                event_count=?, malformed_lines=?, first_timestamp=?, last_timestamp=?,
                total_input_tokens=?, total_output_tokens=?, total_cost=?, indexed_at=?
            WHERE run_name=?""",
            (count, malformed, *aggregate, indexed_at, run_name),
        )

    def _set_meta(self, key: str, value: str) -> None:
        self._connection.execute(
            "INSERT INTO metadata(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    @staticmethod
    def _fts_query(text: str) -> str:
        terms = re.findall(r"[\w-]+", text, flags=re.UNICODE)
        return " AND ".join('"' + term.replace('"', '""') + '"' for term in terms)

    def query_events(
        self,
        text: str = "",
        *,
        facets: Mapping[str, Any] | None = None,
        run_name: str | None = None,
        event_type: str | None = None,
        actor: str | None = None,
        technique: str | None = None,
        verdict: str | None = None,
        execution_id: str | None = None,
        round_id: str | int | None = None,
        inference_id: str | None = None,
        tool_id: str | None = None,
        timestamp_from: str | None = None,
        timestamp_to: str | None = None,
        limit: int = 50,
        offset: int = 0,
        order: str = "desc",
    ) -> dict[str, Any]:
        """Search events with pagination and exact-match structured facets."""
        selected = {
            "run_name": run_name,
            "event_type": event_type,
            "actor": actor,
            "technique": technique,
            "verdict": verdict,
            "execution_id": execution_id,
            "round_id": round_id,
            "inference_id": inference_id,
            "tool_id": tool_id,
        }
        for key, value in (facets or {}).items():
            if key in selected and value not in (None, ""):
                selected[key] = value

        clauses: list[str] = []
        parameters: list[Any] = []
        for column, value in selected.items():
            if value not in (None, ""):
                clauses.append(f"e.{column} = ?")
                parameters.append(str(value))
        if timestamp_from:
            clauses.append("e.timestamp >= ?")
            parameters.append(timestamp_from)
        if timestamp_to:
            clauses.append("e.timestamp <= ?")
            parameters.append(timestamp_to)

        join = ""
        if text and self.fts_enabled and self._fts_query(text):
            join = " JOIN events_fts ON events_fts.rowid = e.id"
            clauses.append("events_fts MATCH ?")
            parameters.append(self._fts_query(text))
        elif text:
            clauses.append("LOWER(e.searchable_text) LIKE LOWER(?)")
            parameters.append(f"%{text}%")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        total = self._connection.execute(
            f"SELECT COUNT(*) FROM events e{join}{where}", parameters
        ).fetchone()[0]
        direction = "ASC" if order.lower() == "asc" else "DESC"
        safe_limit = min(max(int(limit), 1), 1000)
        safe_offset = max(int(offset), 0)
        rows = self._connection.execute(
            f"""SELECT e.* FROM events e{join}{where}
            ORDER BY e.timestamp {direction}, e.sequence {direction}, e.id {direction}
            LIMIT ? OFFSET ?""",
            (*parameters, safe_limit, safe_offset),
        ).fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }

    # A shorter name is convenient for API adapters.
    query = query_events

    def run_summaries(self, *, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        safe_limit = min(max(int(limit), 1), 1000)
        safe_offset = max(int(offset), 0)
        total = self._connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        rows = self._connection.execute(
            """SELECT * FROM runs
            ORDER BY last_timestamp DESC, run_name DESC LIMIT ? OFFSET ?""",
            (safe_limit, safe_offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            verdict_rows = self._connection.execute(
                """SELECT verdict, COUNT(*) AS count FROM events
                WHERE run_name=? AND verdict<>'' GROUP BY verdict ORDER BY verdict""",
                (item["run_name"],),
            ).fetchall()
            item["verdicts"] = {value["verdict"]: value["count"] for value in verdict_rows}
            items.append(item)
        return {"items": items, "total": total, "limit": safe_limit, "offset": safe_offset}

    def status(self) -> dict[str, Any]:
        values = {
            row["key"]: row["value"]
            for row in self._connection.execute("SELECT key, value FROM metadata")
        }
        aggregate = self._connection.execute(
            """SELECT COUNT(*) AS runs, COALESCE(SUM(event_count), 0) AS events,
            COALESCE(SUM(malformed_lines), 0) AS malformed FROM runs"""
        ).fetchone()
        latest = self._connection.execute("SELECT MAX(indexed_at) FROM runs").fetchone()[0]
        return {
            "database": str(self.path),
            "schema_version": int(values.get("schema_version", SCHEMA_VERSION)),
            "fts_enabled": self.fts_enabled,
            "run_count": aggregate["runs"],
            "event_count": aggregate["events"],
            "malformed_lines": aggregate["malformed"],
            "last_indexed_at": latest,
            "last_rebuild_at": values.get("last_rebuild_at"),
            "source_directory": values.get("source_directory"),
        }


__all__ = ["HistoryIndex", "REDACTED", "SCHEMA_VERSION", "redact"]
