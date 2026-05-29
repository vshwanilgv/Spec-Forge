from __future__ import annotations

import json
from pathlib import Path

from openai import OpenAI

from pipeline.agents.base import BaseAgent
from pipeline.models import AgentResult, PlanModel, SpecModel


class PlannerAgent(BaseAgent):
    agent_name = "planner"

    def __init__(self, client: OpenAI, prompts_dir: str, model: str, run_dir: Path) -> None:
        super().__init__(client, prompts_dir, model)
        self._run_dir = run_dir

    def execute(self, context: dict) -> AgentResult:
        spec: SpecModel = context["spec"]
        retry_count: int = context.get("retry_count", 0)

        prompt_template = self._load_prompt()
        prompt = prompt_template.format_map({"spec_json": spec.model_dump_json(indent=2)})

        output, tokens = self._call_llm(prompt)

        try:
            plan = PlanModel(**output)
        except Exception as exc:
            return self._build_result(
                success=False,
                output={"error": str(exc), "raw": output},
                tokens_used=tokens,
                retry_count=retry_count,
            )

        self._write_plan_markdown(plan)

        return self._build_result(
            success=True,
            output=plan.model_dump(),
            tokens_used=tokens,
            retry_count=retry_count,
        )

    def _write_plan_markdown(self, plan: PlanModel) -> None:
        lines: list[str] = [
            "# Implementation Plan\n",
            "## Technical Design Summary\n",
            f"{plan.technical_design_summary}\n",
            "## Implementation Tasks\n",
            *[f"- {task}\n" for task in plan.implementation_tasks],
            "## Impacted Files\n",
            *[f"- `{f}`\n" for f in plan.impacted_files],
            "## Risk Considerations\n",
            *[f"- {risk}\n" for risk in plan.risk_considerations],
            "## Test Strategy\n",
            f"{plan.test_strategy}\n",
        ]
        (self._run_dir / "plan.md").write_text("".join(lines), encoding="utf-8")