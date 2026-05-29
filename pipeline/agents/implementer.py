from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from openai import OpenAI

from pipeline.agents.base import BaseAgent
from pipeline.gates.sandbox import SandboxGuard, SandboxViolation
from pipeline.models import AgentResult, PlanModel, SpecModel


class ImplementerAgent(BaseAgent):
    agent_name = "implementer"

    def __init__(
        self,
        client: OpenAI,
        prompts_dir: str,
        run_dir: Path,
        sandbox: SandboxGuard,
        model: str,
    ) -> None:
        super().__init__(client, prompts_dir, model)
        self._run_dir = run_dir
        self._sandbox = sandbox

    def execute(self, context: dict) -> AgentResult:
        plan: PlanModel = context["plan"]
        spec: SpecModel = context["spec"]
        allowed_dirs: list[str] = context["allowed_dirs"]
        retry_count: int = context.get("retry_count", 0)

        prompt_template = self._load_prompt()
        prompt = prompt_template.format_map(
            {
                "plan_json": plan.model_dump_json(indent=2),
                "acceptance_criteria": json.dumps(spec.acceptance_criteria, indent=2),
                "allowed_dirs": json.dumps(allowed_dirs, indent=2),
            }
        )

        output, tokens = self._call_llm(prompt)

        if "__llm_error__" in output:
            return self._build_result(
                success=False,
                output={"error": f"LLM returned invalid JSON: {output['__llm_error__']}"},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        try:
            files: list[dict] = output["files"]
            change_summary: str = output["change_summary"]
        except KeyError as exc:
            return self._build_result(
                success=False,
                output={"error": f"Missing key in LLM output: {exc}", "raw": output},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        try:
            written = self._write_files(files)
        except SandboxViolation as exc:
            return self._build_result(
                success=False,
                output={"error": str(exc)},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        return self._build_result(
            success=True,
            output={"files": written, "change_summary": change_summary},
            tokens_used=tokens,
            retry_count=retry_count,
        )

    def _write_files(self, files: list[dict]) -> list[str]:
        repo_dir = self._run_dir / "repo"
        written: list[str] = []

        for file_spec in files:
            raw_path: str = file_spec["path"]
            content: str = file_spec["content"]

            rel_path = self._normalize_path(raw_path)
            abs_path = repo_dir / rel_path

            self._sandbox.validate(str(abs_path))

            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            written.append(rel_path)

        return written

    @staticmethod
    def _normalize_path(raw: str) -> str:
        """Strip leading '../' segments the LLM sometimes emits.

        'src/auth.py'        -> 'src/auth.py'   (unchanged)
        '../src/auth.py'     -> 'src/auth.py'
        '../../src/auth.py'  -> 'src/auth.py'
        '/abs/src/auth.py'   -> 'abs/src/auth.py'
        """
        parts = PurePosixPath(raw.lstrip("/")).parts
        clean = [p for p in parts if p != ".."]
        if not clean:
            raise SandboxViolation(f"Path '{raw}' has no valid components after normalisation.")
        return str(PurePosixPath(*clean))