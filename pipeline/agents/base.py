from __future__ import annotations

import json
import time
from pathlib import Path

from openai import BadRequestError, OpenAI, RateLimitError

from pipeline.models import AgentResult

_JSON_RESPONSE_FORMAT: dict = {"type": "json_object"}
_RATE_LIMIT_RETRIES = 5
_RATE_LIMIT_BACKOFF_SECONDS = 15


class BaseAgent:
    agent_name: str

    def __init__(self, client: OpenAI, prompts_dir: str, model: str) -> None:
        self._client = client
        self._prompts_dir = Path(prompts_dir)
        self._model = model

    def _load_prompt(self) -> str:
        prompt_path = self._prompts_dir / f"{self.agent_name}.txt"
        return prompt_path.read_text(encoding="utf-8")

    def _call_llm(self, prompt: str) -> tuple[dict, int]:
        for attempt in range(_RATE_LIMIT_RETRIES):
            try:
                response = self._client.chat.completions.create(
                    model=self._model,
                    response_format=_JSON_RESPONSE_FORMAT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = response.choices[0].message.content or "{}"
                tokens = response.usage.total_tokens if response.usage else 0
                return json.loads(raw), tokens
            except RateLimitError:
                if attempt == _RATE_LIMIT_RETRIES - 1:
                    raise
                wait = _RATE_LIMIT_BACKOFF_SECONDS * (attempt + 1)
                print(f"Rate limit — waiting {wait}s (retry {attempt + 1}/{_RATE_LIMIT_RETRIES - 1})...")
                time.sleep(wait)
            except BadRequestError as exc:
                return {"__llm_error__": str(exc)}, 0

    def _build_result(
        self,
        *,
        success: bool,
        output: dict,
        tokens_used: int,
        retry_count: int = 0,
    ) -> AgentResult:
        return AgentResult(
            agent=self.agent_name,
            success=success,
            output=output,
            retry_count=retry_count,
            tokens_used=tokens_used,
        )