import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./secopsmesh.db")

    # All LLM access (Orchestrator, Root Cause, Risk + Remediation agents,
    # Day 3+) goes through OpenRouter's OpenAI-compatible API rather than
    # calling Anthropic directly.
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

    # Optional shared-secret guarding the /api endpoints (sent as X-API-Key).
    # Left unset by default so local dev and the demo curl commands keep working
    # with no ceremony; set API_KEY in the deployed environment to require it.
    # This is a POC-grade gate, not a substitute for real per-user auth.
    api_key: str | None = os.getenv("API_KEY")


settings = Settings()
