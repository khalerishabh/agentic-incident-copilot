import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

FixAction = Literal["rollback", "restart", "scale", "disable_flag"]
ALL_ACTIONS: list[FixAction] = ["rollback", "restart", "scale", "disable_flag"]

CONFIG_PATH = Path(os.getenv("COPILOT_CONFIG", "copilot.yaml"))
SECRET_KEY_PATTERN = re.compile(r"(^|_)(api_key|token|password|secret|postgres_url|dsn)$", re.I)


class ServiceConfig(BaseModel):
    name: str
    team: str = ""


class LLMConfig(BaseModel):
    provider: Literal["anthropic", "openai", "ollama"] = "anthropic"
    model: str = "claude-sonnet-4-5"
    base_url: str | None = None
    temperature: float = 0.0


class MCPConfig(BaseModel):
    logs_url: str = "http://localhost:9101/mcp"
    metrics_url: str = "http://localhost:9102/mcp"
    github_url: str = "http://localhost:9103/mcp"
    runbook_url: str = "http://localhost:9104/mcp"


class BudgetConfig(BaseModel):
    tokens_per_incident: int = Field(default=60_000, gt=0)


class GuardrailConfig(BaseModel):
    dry_run: bool = True
    allowed_actions: list[FixAction] = Field(default_factory=lambda: list(ALL_ACTIONS))
    max_replicas: int = Field(default=5, ge=1)


class ExecutorConfig(BaseModel):
    backend: Literal["docker", "kubernetes"] = "docker"
    kubernetes_namespaces: list[str] = Field(default_factory=lambda: ["default"])


IDENTIFIER = r"^[A-Za-z_][A-Za-z0-9_]*$"


class LogFieldMap(BaseModel):
    """Names of the fields inside each log line, so any JSON log schema can be read."""

    timestamp: str = Field(default="ts", pattern=IDENTIFIER)
    level: str = Field(default="level", pattern=IDENTIFIER)
    message: str = Field(default="msg", pattern=IDENTIFIER)
    request_id: str = Field(default="request_id", pattern=IDENTIFIER)


class LokiConfig(BaseModel):
    url: str = "http://localhost:3100"
    tenant_id: str | None = None
    username: str | None = None
    password: SecretStr | None = None
    line_format: Literal["json", "logfmt"] = "json"
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=6)


class FileLogsConfig(BaseModel):
    directory: Path = Path("./data/logs")


class LogsIntegration(BaseModel):
    backend: Literal["loki", "file"] = "file"
    service_label: str = Field(default="service", pattern=IDENTIFIER)
    fields: LogFieldMap = Field(default_factory=LogFieldMap)
    max_lines: int = Field(default=50, ge=1, le=500)
    max_scan_lines: int = Field(default=2000, ge=100, le=20000)
    max_window_minutes: int = Field(default=1440, ge=1)
    loki: LokiConfig = Field(default_factory=LokiConfig)
    file: FileLogsConfig = Field(default_factory=FileLogsConfig)


class IntegrationsConfig(BaseModel):
    logs: LogsIntegration = Field(default_factory=LogsIntegration)


class SecretsInConfigError(ValueError):
    pass


def _find_secret_keys(data: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}{key}"
            if SECRET_KEY_PATTERN.search(str(key)):
                found.append(path)
            found += _find_secret_keys(value, f"{path}.")
    elif isinstance(data, list):
        for i, item in enumerate(data):
            found += _find_secret_keys(item, f"{prefix}{i}.")
    return found


class _SecretFreeYamlSource(YamlConfigSettingsSource):
    def __call__(self) -> dict[str, Any]:
        data = super().__call__()
        if leaked := _find_secret_keys(data):
            raise SecretsInConfigError(
                f"secrets are not allowed in {CONFIG_PATH}: {', '.join(leaked)}. "
                "Set them as environment variables instead."
            )
        return data


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        yaml_file=CONFIG_PATH,
    )

    environment: str = "dev"
    services: list[ServiceConfig] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    guardrails: GuardrailConfig = Field(default_factory=GuardrailConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)

    postgres_url: SecretStr = SecretStr("postgresql://copilot:copilot@localhost:5432/copilot")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _SecretFreeYamlSource(settings_cls),
            file_secret_settings,
        )

    @property
    def service_names(self) -> set[str]:
        """An empty services list means no fix can target anything: the safe default."""
        return {s.name for s in self.services}


settings = Settings()
