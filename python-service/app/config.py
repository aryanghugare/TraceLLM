"""Application settings, loaded from environment variables (and an optional .env file).

pydantic-settings maps each field to an env var of the same name, case-insensitive:
`mongodb_uri` <- MONGODB_URI, `openai_api_key` <- OPENAI_API_KEY, and so on.
The env var names match the Node service, so both can share one docker-compose / k8s config.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Storage and queue
    mongodb_uri: str = "mongodb://localhost:27017/tracellm"
    redis_url: str = "redis://localhost:6379"
    queue_name: str = "tracellm:inference-logs"
    dead_letter_key: str = "tracellm:failed-logs"

    # LLM providers. Keys can also be sent per request (like the Node API's `apiKey`).
    llm_provider: str = "openai"
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None

    # The web UI does not send a model, so each provider needs a default.
    openai_model: str = "gpt-4o-mini"
    gemini_model: str = "gemini-2.5-flash"
    anthropic_model: str = "claude-haiku-5-5"

    # Worker
    ingestion_worker_concurrency: int = 5
    ingestion_max_tries: int = 3
    worker_metrics_port: int = 9100

    # Agent
    agent_max_steps: int = 5

    def api_key_for(self, provider: str) -> str | None:
        return {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider)

    def default_model_for(self, provider: str) -> str | None:
        return {
            "openai": self.openai_model,
            "gemini": self.gemini_model,
            "anthropic": self.anthropic_model,
        }.get(provider)


@lru_cache
def get_settings() -> Settings:
    """Read settings once per process (lru_cache makes this a cheap singleton)."""
    return Settings()
