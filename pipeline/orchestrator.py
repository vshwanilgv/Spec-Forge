from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from git import Repo as GitRepo
from openai import OpenAI

from pipeline.agents.implementer import ImplementerAgent
from pipeline.agents.planner import PlannerAgent
from pipeline.agents.reviewer import ReviewerAgent
from pipeline.agents.test_generator import TestGeneratorAgent
from pipeline.approval.github_pr import GitHubApproval
from pipeline.approval.webhook import WebhookListener
from pipeline.audit.logger import AuditLogger
from pipeline.config import Config
from pipeline.gates.quality import QualityGateRunner
from pipeline.gates.sandbox import SandboxGuard
from pipeline.models import (
    AgentResult,
    AuditEntry,
    OrchestratorDecision,
    PipelineState,
    PlanModel,
    SpecModel,
)
from pipeline.state.store import StateStore

# Model is read from config at runtime — see _get_decision()
_JSON_RESPONSE_FORMAT: dict = {"type": "json_object"}
# Branch names are built per-run in _handle_checkpoint_1 / _handle_checkpoint_2
_CLONE_URL_TEMPLATE = "https://{token}@github.com/{repo}.git"


class Orchestrator:
    def __init__(
        self,
        spec: SpecModel,
        state: PipelineState,
        state_store: StateStore,
        audit_logger: AuditLogger,
        config: Config,
        run_dir: Path,
    ) -> None:
        self._spec = spec
        self._state = state
        self._state_store = state_store
        self._audit = audit_logger
        self._config = config
        self._run_dir = run_dir
        self._client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
        self._sandbox: SandboxGuard | None = None  # built lazily after repo is cloned
        self._webhook = WebhookListener(config.GITHUB_WEBHOOK_SECRET)
        self._approval: GitHubApproval | None = None
        self._orchestrator_prompt = self._load_orchestrator_prompt()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        import time
        self._webhook.start(self._config.WEBHOOK_PORT)
        # Give uvicorn time to fully bind before opening any PR.
        # Without this, a fast merge can arrive before the listener is ready.
        time.sleep(3)

        while True:
            decision = self._get_decision()
            self._log_decision(decision)
            self._state.current_stage = decision.next_agent
            self._state_store.save(self._state)

            match decision.next_agent:
                case "done":
                    self._finalise()
                    return
                case "abort":
                    self._abort("Orchestrator decided to abort.")
                    return
                case "checkpoint":
                    aborted = self._handle_checkpoint()
                    if aborted:
                        return
                case "quality_gates":
                    aborted = self._handle_quality_gates()
                    if aborted:
                        return
                case agent_name:
                    aborted = self._handle_agent(agent_name, decision.retry_allowed)
                    if aborted:
                        return

    # ------------------------------------------------------------------
    # Orchestrator decision
    # ------------------------------------------------------------------

    def _load_orchestrator_prompt(self) -> str:
        path = Path(self._config.PROMPTS_DIR) / "orchestrator.txt"
        return path.read_text(encoding="utf-8")

    def _get_decision(self) -> OrchestratorDecision:
        """Deterministic routing for the happy path.

        The pipeline sequence is fixed so we route by inspecting state directly.
        The LLM is only called when an agent has just failed, to decide retry vs abort.
        This eliminates routing loops and cuts token usage dramatically.
        """
        s = self._state
        results = s.agent_results

        def last_success(agent: str) -> bool:
            return any(r.agent == agent and r.success for r in results)

        if results and not results[-1].success:
            return self._get_retry_decision()

        if not last_success("planner"):
            return OrchestratorDecision(next_agent="planner", reasoning="No successful plan yet.", retry_allowed=False)
        if not s.checkpoint_1_merged:
            return OrchestratorDecision(next_agent="checkpoint", reasoning="Plan ready for human review.", retry_allowed=False)
        if not last_success("implementer"):
            return OrchestratorDecision(next_agent="implementer", reasoning="Implementing approved plan.", retry_allowed=False)
        if not last_success("test_generator"):
            return OrchestratorDecision(next_agent="test_generator", reasoning="Generating tests.", retry_allowed=False)
        if not last_success("reviewer"):
            return OrchestratorDecision(next_agent="reviewer", reasoning="Reviewing generated code.", retry_allowed=False)
        if not s.quality_gates_passed:
            return OrchestratorDecision(next_agent="quality_gates", reasoning="Running quality gates.", retry_allowed=False)
        if not s.checkpoint_2_merged:
            return OrchestratorDecision(next_agent="checkpoint", reasoning="Quality gates passed, awaiting deploy approval.", retry_allowed=False)
        return OrchestratorDecision(next_agent="done", reasoning="All stages complete.", retry_allowed=False)

    def _get_retry_decision(self) -> OrchestratorDecision:
        """Deterministic retry: re-route to the failed agent or abort if cap exceeded."""
        failed = self._state.agent_results[-1]
        retry_count = self._state.retry_counts.get(failed.agent, 0)
        if retry_count < self._config.MAX_RETRIES:
            return OrchestratorDecision(
                next_agent=failed.agent,
                reasoning=f"Retrying {failed.agent} (attempt {retry_count + 1}/{self._config.MAX_RETRIES}).",
                retry_allowed=True,
            )
        return OrchestratorDecision(
            next_agent="abort",
            reasoning=f"Max retries ({self._config.MAX_RETRIES}) exceeded for {failed.agent}.",
            retry_allowed=False,
        )
    def _log_decision(self, decision: OrchestratorDecision) -> None:
        self._audit.log(
            AuditEntry(
                run_id=self._state.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="orchestrator_decision",
                payload=decision.model_dump(),
            )
        )

    # ------------------------------------------------------------------
    # Agent dispatch
    # ------------------------------------------------------------------

    def _handle_agent(self, agent_name: str, retry_allowed: bool) -> bool:
        """Returns True if the pipeline was aborted.

        On failure the retry count is incremented and the loop continues,
        letting the orchestrator decide in the next iteration whether to
        retry or abort. The hard cap (MAX_RETRIES) is enforced here.
        """
        retry_count = self._state.retry_counts.get(agent_name, 0)
        context = self._build_context(agent_name, retry_count)
        agent = self._build_agent(agent_name)

        self._audit.log(
            AuditEntry(
                run_id=self._state.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="agent_called",
                payload={"agent": agent_name, "retry_count": retry_count},
            )
        )

        try:
            result = agent.execute(context)
        except Exception as exc:
            result = AgentResult(
                agent=agent_name,
                success=False,
                output={"error": f"Unhandled exception in agent: {exc}"},
                retry_count=retry_count,
                tokens_used=0,
            )

        self._audit.log(
            AuditEntry(
                run_id=self._state.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="agent_result",
                payload=result.model_dump(),
            )
        )

        self._state.agent_results.append(result)

        if not result.success:
            if retry_count >= self._config.MAX_RETRIES:
                self._abort(f"Agent '{agent_name}' failed after {retry_count} retries.")
                return True
            self._state.retry_counts[agent_name] = retry_count + 1
            self._state_store.save(self._state)
            return False

        self._state.retry_counts[agent_name] = 0
        self._state_store.save(self._state)
        return False

    def _build_agent(
        self,
        agent_name: str,
    ) -> PlannerAgent | ImplementerAgent | TestGeneratorAgent | ReviewerAgent:
        match agent_name:
            case "planner":
                return PlannerAgent(
                    client=self._client,
                    prompts_dir=self._config.PROMPTS_DIR,
                    run_dir=self._run_dir,
                    model=self._config.LLM_MODEL,
                )
            case "implementer":
                return ImplementerAgent(
                    client=self._client,
                    prompts_dir=self._config.PROMPTS_DIR,
                    run_dir=self._run_dir,
                    sandbox=self._get_sandbox(),
                    model=self._config.LLM_MODEL,
                )
            case "test_generator":
                return TestGeneratorAgent(
                    client=self._client,
                    prompts_dir=self._config.PROMPTS_DIR,
                    run_dir=self._run_dir,
                    model=self._config.LLM_MODEL,
                )
            case "reviewer":
                return ReviewerAgent(
                    client=self._client,
                    prompts_dir=self._config.PROMPTS_DIR,
                    run_dir=self._run_dir,
                    model=self._config.LLM_MODEL,
                )
            case _:
                raise ValueError(f"Unknown agent: '{agent_name}'")

    def _build_context(self, agent_name: str, retry_count: int) -> dict:
        base: dict = {"retry_count": retry_count}
        match agent_name:
            case "planner":
                return {**base, "spec": self._spec}
            case "implementer":
                return {
                    **base,
                    "spec": self._spec,
                    "plan": self._extract_plan(),
                    "allowed_dirs": self._config.allowed_dirs_list,
                }
            case "test_generator":
                # Truncate file contents to keep prompt size manageable for the LLM.
                raw_files = self._extract_source_files()
                source_files = [
                    {"path": f["path"], "content": f["content"][:1500]}
                    for f in raw_files
                ]
                return {
                    **base,
                    "spec": self._spec,
                    "source_files": source_files,
                }
            case "reviewer":
                return {
                    **base,
                    "spec": self._spec,
                    "plan": self._extract_plan(),
                    "generated_files": self._extract_all_generated_files(),
                }
            case _:
                raise ValueError(f"No context builder for agent: '{agent_name}'")

    # ------------------------------------------------------------------
    # Quality gates
    # ------------------------------------------------------------------

    def _handle_quality_gates(self) -> bool:
        """Returns True if the pipeline was aborted."""
        repo_path = str(self._run_dir / "repo")
        runner = QualityGateRunner(repo_path)
        results = runner.run_all()

        for gate in results:
            self._audit.log(
                AuditEntry(
                    run_id=self._state.run_id,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    event_type="gate_result",
                    payload={
                        "tool": gate.tool,
                        "passed": gate.passed,
                        "output": gate.output,
                    },
                )
            )

        failed = [r.tool for r in results if not r.passed]
        if failed:
            self._abort(f"Quality gates failed: {', '.join(failed)}")
            return True
        self._state.quality_gates_passed = True
        self._state_store.save(self._state)
        return False

    # ------------------------------------------------------------------
    # Checkpoint (GitHub PR + webhook)
    # ------------------------------------------------------------------

    def _handle_checkpoint(self) -> bool:
        """Returns True if the pipeline was aborted."""
        if not self._state.checkpoint_1_merged:
            return self._handle_checkpoint_1()
        if not self._state.checkpoint_2_merged:
            return self._handle_checkpoint_2()
        return False

    def _handle_checkpoint_1(self) -> bool:
        self._ensure_repo_cloned()
        approval = self._get_approval()
        plan_path = str(self._run_dir / "plan.md")

        plan_branch = f"pipeline/plan-{self._state.run_id}"
        pr_url, pr_number = approval.open_plan_pr(plan_branch, plan_path)
        print(f"Checkpoint 1 — plan review PR: {pr_url}")

        self._state.status = "awaiting_approval"
        self._state_store.save(self._state)

        merged = approval.wait_for_merge(pr_number)

        if not merged:
            self._abort("Checkpoint 1 PR closed without merging.")
            return True

        self._state.checkpoint_1_merged = True
        self._state.current_stage = "implementer"
        self._state.status = "running"
        self._state_store.save(self._state)
        return False

    def _handle_checkpoint_2(self) -> bool:
        approval = self._get_approval()
        changed_files = self._extract_source_file_paths()

        code_branch = f"pipeline/code-{self._state.run_id}"
        pr_url, pr_number = approval.open_code_pr(code_branch, changed_files)
        print(f"Checkpoint 2 — deploy review PR: {pr_url}")

        self._state.status = "awaiting_approval"
        self._state_store.save(self._state)

        merged = approval.wait_for_merge(pr_number)

        if not merged:
            self._abort("Checkpoint 2 PR closed without merging.")
            return True

        self._state.checkpoint_2_merged = True
        self._state.current_stage = "done"
        self._state.status = "running"
        self._state_store.save(self._state)
        return False

    # ------------------------------------------------------------------
    # Finalise / abort
    # ------------------------------------------------------------------

    def _finalise(self) -> None:
        self._state.status = "completed"
        self._state_store.save(self._state)
        self._audit.log(
            AuditEntry(
                run_id=self._state.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="pipeline_completed",
                payload={"run_id": self._state.run_id},
            )
        )
        print(f"Pipeline completed successfully: {self._state.run_id}")

    def _abort(self, reason: str) -> None:
        self._state.status = "aborted"
        self._state_store.save(self._state)
        self._audit.log(
            AuditEntry(
                run_id=self._state.run_id,
                timestamp=datetime.now(timezone.utc).isoformat(),
                event_type="pipeline_failed",
                payload={"reason": reason},
            )
        )
        print(f"Pipeline aborted: {reason}")

    # ------------------------------------------------------------------
    # Data extraction from agent results
    # ------------------------------------------------------------------

    def _last_successful_result(self, agent_name: str) -> AgentResult | None:
        for result in reversed(self._state.agent_results):
            if result.agent == agent_name and result.success:
                return result
        return None

    def _extract_plan(self) -> PlanModel:
        result = self._last_successful_result("planner")
        if result is None:
            raise RuntimeError("No successful planner result in state.")
        return PlanModel(**result.output)

    def _extract_source_files(self) -> list[dict]:
        result = self._last_successful_result("implementer")
        if result is None:
            raise RuntimeError("No successful implementer result in state.")
        repo_dir = self._run_dir / "repo"
        files: list[dict] = []
        for rel_path in result.output.get("files", []):
            abs_path = repo_dir / rel_path
            if abs_path.exists():
                files.append(
                    {"path": rel_path, "content": abs_path.read_text(encoding="utf-8")}
                )
        return files

    def _extract_source_file_paths(self) -> list[str]:
        result = self._last_successful_result("implementer")
        if result is None:
            raise RuntimeError("No successful implementer result in state.")
        return result.output.get("files", [])

    def _extract_all_generated_files(self) -> list[dict]:
        source = self._extract_source_files()
        test_result = self._last_successful_result("test_generator")
        if test_result is None:
            return source
        repo_dir = self._run_dir / "repo"
        tests: list[dict] = []
        for rel_path in test_result.output.get("files", []):
            abs_path = repo_dir / rel_path
            if abs_path.exists():
                tests.append(
                    {"path": rel_path, "content": abs_path.read_text(encoding="utf-8")}
                )
        return source + tests

    # ------------------------------------------------------------------
    # Repo + approval initialisation
    # ------------------------------------------------------------------

    def _summarise_state_for_routing(self) -> str:
        """Return a token-efficient state summary for orchestrator routing decisions.

        Strips verbose agent output fields — the orchestrator only needs to know
        which agents succeeded, not the full content they produced.
        """
        import json
        state = self._state.model_dump()
        state["agent_results"] = [
            {
                "agent": r["agent"],
                "success": r["success"],
                "retry_count": r["retry_count"],
            }
            for r in state["agent_results"]
        ]
        return json.dumps(state, indent=2)

    def _get_sandbox(self) -> SandboxGuard:
        if self._sandbox is None:
            repo_dir = self._run_dir / "repo"
            self._sandbox = SandboxGuard([str(repo_dir)])
        return self._sandbox

    def _ensure_repo_cloned(self) -> None:
        repo_dir = self._run_dir / "repo"
        if repo_dir.exists():
            return
        clone_url = _CLONE_URL_TEMPLATE.format(
            token=self._config.GITHUB_TOKEN,
            repo=self._config.GITHUB_TARGET_REPO,
        )
        GitRepo.clone_from(clone_url, str(repo_dir))

    def _get_approval(self) -> GitHubApproval:
        if self._approval is None:
            self._approval = GitHubApproval(
                config=self._config,
                run_id=self._state.run_id,
                audit_logger=self._audit,
                webhook_listener=self._webhook,
                repo_local_path=str(self._run_dir / "repo"),
            )
        return self._approval