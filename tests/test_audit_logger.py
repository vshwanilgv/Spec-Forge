from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline.audit.logger import AuditLogger
from pipeline.models import AuditEntry


def _make_entry(
    run_id: str = "run_test",
    event_type: str = "spec_ingested",
    payload: dict | None = None,
) -> AuditEntry:
    return AuditEntry(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        payload=payload or {"key": "value"},
    )


def _read_lines(log_file: Path) -> list[str]:
    return [line for line in log_file.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestAuditLoggerSingleEntry:
    def test_log_creates_file_if_not_exists(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry())
        assert log_file.exists()

    def test_single_entry_written_as_valid_json(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry())
        lines = _read_lines(log_file)
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["run_id"] == "run_test"

    def test_entry_event_type_is_preserved(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry(event_type="agent_called"))
        parsed = json.loads(_read_lines(log_file)[0])
        assert parsed["event_type"] == "agent_called"

    def test_entry_payload_is_preserved(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry(payload={"agent": "planner", "retry_count": 0}))
        parsed = json.loads(_read_lines(log_file)[0])
        assert parsed["payload"]["agent"] == "planner"
        assert parsed["payload"]["retry_count"] == 0

    def test_entry_timestamp_is_preserved(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        entry = _make_entry()
        logger.log(entry)
        parsed = json.loads(_read_lines(log_file)[0])
        assert parsed["timestamp"] == entry.timestamp


class TestAuditLoggerAppendSemantics:
    def test_multiple_entries_all_written(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        for i in range(5):
            logger.log(_make_entry(run_id=f"run_{i}"))
        assert len(_read_lines(log_file)) == 5

    def test_existing_content_is_never_truncated(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry(run_id="first"))
        content_after_first = log_file.read_text(encoding="utf-8")
        logger.log(_make_entry(run_id="second"))
        content_after_second = log_file.read_text(encoding="utf-8")
        assert content_after_second.startswith(content_after_first)

    def test_second_logger_instance_appends_to_existing_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        AuditLogger(str(log_file)).log(_make_entry(run_id="run_a"))
        AuditLogger(str(log_file)).log(_make_entry(run_id="run_b"))
        lines = _read_lines(log_file)
        assert len(lines) == 2

    def test_entries_written_in_order(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        run_ids = [f"run_{i}" for i in range(10)]
        for run_id in run_ids:
            logger.log(_make_entry(run_id=run_id))
        parsed_ids = [json.loads(line)["run_id"] for line in _read_lines(log_file)]
        assert parsed_ids == run_ids

    def test_all_event_types_written_correctly(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        event_types = [
            "spec_ingested",
            "agent_called",
            "agent_result",
            "orchestrator_decision",
            "checkpoint_opened",
            "checkpoint_approved",
            "gate_result",
            "pipeline_completed",
            "pipeline_failed",
        ]
        for et in event_types:
            logger.log(_make_entry(event_type=et))
        lines = _read_lines(log_file)
        assert len(lines) == len(event_types)
        for line, expected_et in zip(lines, event_types):
            assert json.loads(line)["event_type"] == expected_et


class TestAuditLoggerJsonlValidity:
    def test_every_line_is_independently_parseable(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        for i in range(20):
            logger.log(_make_entry(run_id=f"run_{i}"))
        for line in _read_lines(log_file):
            parsed = json.loads(line)
            assert "run_id" in parsed
            assert "timestamp" in parsed
            assert "event_type" in parsed
            assert "payload" in parsed

    def test_no_trailing_garbage_between_entries(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        logger.log(_make_entry())
        logger.log(_make_entry())
        raw = log_file.read_text(encoding="utf-8")
        for line in raw.splitlines():
            if line.strip():
                json.loads(line)


class TestAuditLoggerThreadSafety:
    def test_concurrent_writes_all_land(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        thread_count = 30

        def write(index: int) -> None:
            logger.log(_make_entry(run_id=f"run_{index}"))

        threads = [threading.Thread(target=write, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        lines = _read_lines(log_file)
        assert len(lines) == thread_count

    def test_concurrent_writes_produce_unique_run_ids(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        thread_count = 30

        def write(index: int) -> None:
            logger.log(_make_entry(run_id=f"run_{index}"))

        threads = [threading.Thread(target=write, args=(i,)) for i in range(thread_count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        run_ids = {json.loads(line)["run_id"] for line in _read_lines(log_file)}
        assert len(run_ids) == thread_count

    def test_concurrent_writes_never_corrupt_json(self, tmp_path: Path) -> None:
        log_file = tmp_path / "audit.jsonl"
        logger = AuditLogger(str(log_file))
        errors: list[Exception] = []

        def write_and_collect_errors(index: int) -> None:
            try:
                logger.log(_make_entry(run_id=f"run_{index}"))
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=write_and_collect_errors, args=(i,))
            for i in range(40)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for line in _read_lines(log_file):
            json.loads(line)
