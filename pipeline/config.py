from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

    # LLM — works with any OpenAI-compatible provider 
    LLM_API_KEY: str
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MODEL: str = "gpt-4o"
    # Orchestrator uses a smaller/faster model — routing decisions don't need a 70B model
    LLM_ORCHESTRATOR_MODEL: str = ""  # defaults to LLM_MODEL if empty

    @property
    def orchestrator_model(self) -> str:
        return self.LLM_ORCHESTRATOR_MODEL or self.LLM_MODEL

    # GitHub
    GITHUB_TOKEN: str
    GITHUB_TARGET_REPO: str
    GITHUB_SOURCE_REPO: str
    GITHUB_WEBHOOK_SECRET: str
    PIPELINE_BASE_BRANCH: str = "main"

    # Pipeline behaviour
    ALLOWED_DIRS: str = "src:tests"
    MAX_RETRIES: int = 3
    WEBHOOK_PORT: int = 8080
    NGROK_AUTH_TOKEN: str
    NGROK_DOMAIN: str = ""

    # Paths
    LOG_DIR: str = "./runs"
    PROMPTS_DIR: str = "./prompts"

    @property
    def allowed_dirs_list(self) -> list[str]:
        return [d.strip() for d in self.ALLOWED_DIRS.split(":") if d.strip()]


@lru_cache(maxsize=1)
def get_config() -> Config:
    return Config()