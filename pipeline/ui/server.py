from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

app = FastAPI(title="Spec-Forge UI")

_UI_DIR = Path(__file__).parent

class RunRequest(BaseModel):
    spec_yaml: str

@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (_UI_DIR / "index.html").read_text(encoding="utf-8")


@app.post("/api/runs")
async def start_run(request: RunRequest) -> dict:
    from pipeline.config import get_config

    config = get_config()

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"run_{timestamp}"

    spec_path = Path(config.LOG_DIR) / f"ui_spec_{run_id}.yaml"
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(request.spec_yaml, encoding="utf-8")

    def _run() -> None:
        from pipeline.main import run_command
        try:
            run_command(str(spec_path))
        except SystemExit:
            pass
        except Exception as exc:
            err_path = Path(config.LOG_DIR) / run_id / "ui_error.txt"
            err_path.parent.mkdir(parents=True, exist_ok=True)
            err_path.write_text(str(exc), encoding="utf-8")

    thread = threading.Thread(target=_run, daemon=True, name=f"pipeline-{run_id}")
    thread.start()

    return {"run_id": run_id}


@app.get("/api/runs/{run_id}/stream")
async def stream_events(run_id: str) -> StreamingResponse:
    from pipeline.config import get_config

    config = get_config()
    log_path = Path(config.LOG_DIR) / run_id / "audit.jsonl"

    async def _generate():
        # Wait up to 15 seconds for the run directory to appear
        for _ in range(30):
            if log_path.exists():
                break
            await asyncio.sleep(0.5)

        if not log_path.exists():
            yield f"data: {json.dumps({'event_type': 'pipeline_failed', 'payload': {'reason': 'Run directory not found'}})}\n\n"
            return

        position = 0
        done = False

        while not done:
            try:
                with open(log_path, "r", encoding="utf-8") as fh:
                    fh.seek(position)
                    chunk = fh.read()
                    position = fh.tell()

                for line in chunk.splitlines():
                    if not line.strip():
                        continue
                    entry = json.loads(line)
                    yield f"data: {json.dumps(entry)}\n\n"
                    if entry["event_type"] in ("pipeline_completed", "pipeline_failed"):
                        done = True
                        break

            except Exception:
                pass

            if not done:
                await asyncio.sleep(0.5)

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{run_id}/plan")
async def get_plan(run_id: str) -> dict:
    from pipeline.config import get_config

    config = get_config()
    plan_path = Path(config.LOG_DIR) / run_id / "plan.md"

    if not plan_path.exists():
        raise HTTPException(status_code=404, detail="Plan not found")

    return {"content": plan_path.read_text(encoding="utf-8")}


@app.get("/api/runs/{run_id}/files")
async def get_files(run_id: str) -> dict:
    from pipeline.config import get_config

    config = get_config()
    repo_dir = Path(config.LOG_DIR) / run_id / "repo"

    if not repo_dir.exists():
        raise HTTPException(status_code=404, detail="Repo not found")

    files: list[dict] = []
    for py_file in sorted(repo_dir.rglob("*.py")):
        rel = str(py_file.relative_to(repo_dir))
        if "__pycache__" in rel or ".broken" in rel:
            continue
        files.append({
            "path": rel,
            "content": py_file.read_text(encoding="utf-8"),
            "lines": py_file.read_text(encoding="utf-8").count("\n"),
        })

    return {"files": files}