from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-5"
    ollama_base_url: str = "http://localhost:11434"

    postgres_url: str = "postgresql://copilot:copilot@localhost:5432/copilot"

    mcp_logs_url: str = "http://localhost:9101/mcp"
    mcp_metrics_url: str = "http://localhost:9102/mcp"
    mcp_github_url: str = "http://localhost:9103/mcp"
    mcp_runbook_url: str = "http://localhost:9104/mcp"

    token_budget_per_incident: int = 60_000
    known_services: tuple[str, ...] = ("gateway", "orders", "payments", "inventory")


settings = Settings()
