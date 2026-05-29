from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from pipeline.agents.base import BaseAgent
from pipeline.models import AgentResult, SpecModel


class TestGeneratorAgent(BaseAgent):
    agent_name = "test_generator"

    def __init__(self, client: OpenAI, prompts_dir: str, model: str, run_dir: Path) -> None:
        super().__init__(client, prompts_dir, model)
        self._run_dir = run_dir

    def execute(self, context: dict) -> AgentResult:
        source_files: list[dict] = context["source_files"]
        spec: SpecModel = context["spec"]
        retry_count: int = context.get("retry_count", 0)

        prompt_template = self._load_prompt()
        prompt = prompt_template.format_map(
            {
                "source_files_json": json.dumps(source_files, indent=2),
                "acceptance_criteria": json.dumps(spec.acceptance_criteria, indent=2),
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
        except KeyError as exc:
            return self._build_result(
                success=False,
                output={"error": f"Missing key in LLM output: {exc}", "raw": output},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        written = self._write_test_files(files)

        return self._build_result(
            success=True,
            output={"files": written},
            tokens_used=tokens,
            retry_count=retry_count,
        )

    def _write_test_files(self, files: list[dict]) -> list[str]:
        repo_dir = self._run_dir / "repo"
        written: list[str] = []

        for file_spec in files:
            rel_path: str = file_spec["path"]
            content: str = file_spec["content"]
            abs_path = repo_dir / rel_path

            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            written.append(rel_path)

        return written