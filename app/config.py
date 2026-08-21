import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./secopsmesh.db")

    # LLM Provider selection: "openrouter" (default) or "azure"
    llm_provider: str = os.getenv("LLM_PROVIDER", "openrouter").lower()

    # ===== OpenRouter Configuration =====
    # All LLM access (Orchestrator, Root Cause, Risk + Remediation agents,
    # Day 3+) can go through OpenRouter's OpenAI-compatible API rather than
    # calling Anthropic directly.
    openrouter_api_key: str | None = os.getenv("OPENROUTER_API_KEY")
    openrouter_base_url: str = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    openrouter_model: str = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-5")

    # ===== Azure OpenAI Configuration =====
    # Alternative: Use Azure OpenAI Service with Azure AD authentication
    # Can use either resource_name (preferred) or full endpoint URL
    azure_openai_resource_name: str | None = os.getenv("AZURE_OPENAI_RESOURCE_NAME")
    azure_openai_endpoint: str | None = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    azure_openai_deployment_name: str | None = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    # Optional: API key-based auth (if not using Azure AD)
    azure_openai_api_key: str | None = os.getenv("AZURE_OPENAI_API_KEY")
    # Azure Cognitive Services scope for token provider
    azure_cognitive_services_scope: str = "https://cognitiveservices.azure.com/.default"

    # Azure AD credentials (read from system environment if set)
    # These are typically set at system level, not in .env
    azure_client_id: str | None = os.getenv("AZURE_CLIENT_ID")
    azure_client_secret: str | None = os.getenv("AZURE_CLIENT_SECRET")
    azure_tenant_id: str | None = os.getenv("AZURE_TENANT_ID")

    # Optional shared-secret guarding the /api endpoints (sent as X-API-Key).
    # Left unset by default so local dev and the demo curl commands keep working
    # with no ceremony; set API_KEY in the deployed environment to require it.
    # This is a POC-grade gate, not a substitute for real per-user auth.
    api_key: str | None = os.getenv("API_KEY")

    # Feature Flags
    # Connector selection mode: hard-coded (default) or fully agentic
    use_agentic_connector_selection: bool = (
        os.getenv("USE_AGENTIC_CONNECTOR_SELECTION", "false").lower()
        in ("true", "1", "yes")
    )


settings = Settings()
