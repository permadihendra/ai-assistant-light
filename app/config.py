from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # ── Telegram ──────────────────────────────────────────
    telegram_token: str = ""
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    allowed_chat_ids: list[int] = []

    # ── LLM routing ───────────────────────────────────────
    # Default: Gemini 2.0 Flash (free tier — 1,500 req/day, no credit card)
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash-lite"
    llm_max_tokens: int = 1024
    llm_timeout: float = 30.0

    # ── Per-provider credentials ──────────────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openrouter_api_key: str = ""
    gemini_api_key: str = ""
    opencode_base_url: str = "http://localhost:8080/v1"
    opencode_api_key: str = ""
    zen_base_url: str = "http://localhost:3000/v1"
    zen_api_key: str = ""

    # ── Web Search ───────────────────────────────────────
    search_results: int = 5
    # DuckDuckGo is the default provider (free, no API key).
    # Set brave_api_key if you switch to Brave Search API.
    brave_api_key: str = ""

    # ── Script runner ─────────────────────────────────────
    scripts_dir: str = "scripts"
    script_timeout: int = 10

    # ── Database ──────────────────────────────────────────
    db_path: str = "data/assistant.db"

    # ── AI Personality ──────────────────────────────────────
    # Injected into all LLM prompts — tone, style, humor
    ai_personality: str = ""

    # ── Summarizer ────────────────────────────────────────
    summarize_every_n_messages: int = 50
    summarize_max_chars: int = 8000

    @field_validator("allowed_chat_ids", mode="before")
    @classmethod
    def coerce_chat_ids(cls, v):
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    @field_validator("llm_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        allowed = {"anthropic", "openai", "openrouter", "gemini", "opencode", "zen"}
        if v not in allowed:
            raise ValueError(f"llm_provider must be one of: {allowed}")
        return v


# Module-level singleton — import this everywhere, never instantiate Settings elsewhere
settings = Settings()
