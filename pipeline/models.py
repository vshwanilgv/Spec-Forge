from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SpecModel(BaseModel):
    feature_objective: str
    user_story: str
    business_rules: list[str]
    acceptance_criteria: list[str]
    non_functional_requirements: list[str]
    out_of_scope: list[str]
    raw_format: Literal["yaml", "json", "markdown"]
    spec_hash: str
    version: str


class PlanModel(BaseModel):
    implementation_tasks: list[str]
    technical_design_summary: str
    impacted_files: list[str]
    risk_considerations: list[str]
    test_strategy: str


class AgentResult(BaseModel):
    agent: str
    success: bool
    output: dict
    retry_count: int
    tokens_used: int


class OrchestratorDecision(BaseModel):
    next_agent: Literal[
        "planner",
        "implementer",
        "test_generator",
        "reviewer",
        "quality_gates",
        "checkpoint",
        "done",
        "abort",
    ]
    reasoning: str
    retry_allowed: bool


class PipelineState(BaseModel):
    run_id: str
    spec_version: str
    current_stage: str
    agent_results: list[AgentResult] = Field(default_factory=list)
    checkpoint_1_merged: bool = False
    checkpoint_2_merged: bool = False
    quality_gates_passed: bool = False
    retry_counts: dict[str, int] = Field(default_factory=dict)
    status: Literal["running", "awaiting_approval", "completed", "failed", "aborted"] = "running"


class AuditEntry(BaseModel):
    run_id: str
    timestamp: str
    event_type: Literal[
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
    payload: dict