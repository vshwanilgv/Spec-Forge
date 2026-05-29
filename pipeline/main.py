from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from pipeline.audit.logger import AuditLogger
from pipeline.config import get_config
from pipeline.models import AuditEntry, PipelineState, SpecModel
from pipeline.state.store import StateStore

SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".md": "markdown",
}


def _detect_format(path: Path) -> str:
    fmt = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if fmt is None:
        _exit_with_error(
            f"Unsupported spec extension '{path.suffix}'. "
            f"Accepted: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return fmt 


def _exit_with_error(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def _load_raw(path: Path) -> tuple[str, dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    fmt = _detect_format(path)
    if fmt == "yaml":
        data = yaml.safe_load(raw)
    elif fmt == "json":
        data = json.loads(raw)
    else:
        _exit_with_error("Markdown spec parsing is not yet implemented.")
    return raw, data


def _compute_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_spec_model(data: dict[str, Any], raw: str, fmt: str) -> SpecModel:
    required_fields = [
        "feature_objective",
        "user_story",
        "business_rules",
        "acceptance_criteria",
        "non_functional_requirements",
        "out_of_scope",
    ]
    missing = [f for f in required_fields if f not in data]
    if missing:
        _exit_with_error(f"Spec is missing required fields: {', '.join(missing)}")

    version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return SpecModel(
        **{f: data[f] for f in required_fields},
        raw_format=fmt,
        spec_hash=_compute_hash(raw),
        version=version,
    )


def _initialise_run(run_id: str, config_log_dir: str) -> Path:
    run_dir = Path(config_log_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _build_initial_state(run_id: str, spec: SpecModel) -> PipelineState:
    return PipelineState(
        run_id=run_id,
        spec_version=spec.version,
        current_stage="spec_ingested",
        status="running",
    )


def run_command(spec_path: str) -> None:
    config = get_config()
    path = Path(spec_path)

    if not path.exists():
        _exit_with_error(f"Spec file not found: {spec_path}")

    raw, data = _load_raw(path)
    fmt = _detect_format(path)
    spec = _build_spec_model(data, raw, fmt)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run_{timestamp}"
    run_dir = _initialise_run(run_id, config.LOG_DIR)

    state = _build_initial_state(run_id, spec)
    state_store = StateStore(str(run_dir / "state.json"))
    state_store.save(state)

    audit_logger = AuditLogger(str(run_dir / "audit.jsonl"))
    audit_logger.log(
        AuditEntry(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="spec_ingested",
            payload={
                "spec_hash": spec.spec_hash,
                "spec_version": spec.version,
                "raw_format": spec.raw_format,
                "feature_objective": spec.feature_objective,
            },
        )
    )

    print(f"Run initialised: {run_id}")
    print(f"State:           {run_dir / 'state.json'}")
    print(f"Audit log:       {run_dir / 'audit.jsonl'}")

    from pipeline.orchestrator import Orchestrator

    orchestrator = Orchestrator(
        spec=spec,
        state=state,
        state_store=state_store,
        audit_logger=audit_logger,
        config=config,
        run_dir=run_dir,
    )
    orchestrator.run()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.main",
        description="AI-native spec-driven development pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Execute a pipeline run from a spec file")
    run_parser.add_argument("--spec", required=True, metavar="PATH", help="Path to the spec file")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command == "run":
        run_command(args.spec)


if __name__ == "__main__":
    main()
