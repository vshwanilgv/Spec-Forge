from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from pipeline.agents.base import BaseAgent
from pipeline.models import AgentResult, PlanModel, SpecModel

_PASSING_SCORE_THRESHOLD = 4


class ReviewerAgent(BaseAgent):
    agent_name = "reviewer"

    def __init__(self, client: OpenAI, prompts_dir: str, model: str, run_dir: Path) -> None:
        super().__init__(client, prompts_dir, model)
        self._run_dir = run_dir

    def execute(self, context: dict) -> AgentResult:
        spec: SpecModel = context["spec"]
        plan: PlanModel = context["plan"]
        generated_files: list[dict] = context["generated_files"]
        retry_count: int = context.get("retry_count", 0)

        prompt_template = self._load_prompt()
        prompt = prompt_template.format_map(
            {
                "spec_json": spec.model_dump_json(indent=2),
                "plan_json": plan.model_dump_json(indent=2),
                "generated_files_json": json.dumps(generated_files, indent=2),
            }
        )

        output, tokens = self._call_llm(prompt)

        try:
            passed: bool = bool(output["passed"])
            score: int = int(output["score"])
            issues: list[str] = output.get("issues", [])
            suggestions: list[str] = output.get("suggestions", [])
        except (KeyError, ValueError) as exc:
            return self._build_result(
                success=False,
                output={"error": f"Malformed review response: {exc}", "raw": output},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        review_passed = score >= _PASSING_SCORE_THRESHOLD

        return self._build_result(
            success=review_passed,
            output={
                "passed": passed,
                "score": score,
                "issues": issues,
                "suggestions": suggestions,
            },
            tokens_used=tokens,
            retry_count=retry_count,
        )
