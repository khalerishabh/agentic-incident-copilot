import os
import re
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

FixAction = Literal["rollback", "restart", "scale", "disable_flag"]
ALL_ACTIONS: list[FixAction] = ["rollback", "restart", "scale", "disable_flag"]

# Plain variables in .env (GITHUB_TOKEN, OPENAI_API_KEY, LANGFUSE_*) are read by libraries
# straight from the environment, so load the file into it. Real env vars still win.
load_dotenv(override=False)

CONFIG_PATH = Path(os.getenv("COPILOT_CONFIG", "copilot.yaml"))
SECRET_KEY_PATTERN = re.compile(r"(^|_)(api_key|token|password|secret|postgres_url|dsn)$", re.I)


REPO = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
METRIC = r"^[a-zA-Z_:][a-zA-Z0-9_:]*$"
SAFE_REGEX = r'^[^"\\]+$'


class ServiceConfig(BaseModel):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
    team: str = ""
    repo: str | None = Field(default=None, pattern=REPO)
    branch: str | None = None
    paths: list[str] = Field(default_factory=list)


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


class MetricNames(BaseModel):
    """Metric and label names, so the tools work with any instrumentation conventions."""

    requests_total: str = Field(default="http_requests_total", pattern=METRIC)
    duration_bucket: str = Field(default="http_request_duration_seconds_bucket", pattern=METRIC)
    status_label: str = Field(default="status", pattern=IDENTIFIER)
    error_status_regex: str = Field(default="5..", pattern=SAFE_REGEX)
    upstream_errors_total: str | None = Field(default="upstream_errors_total", pattern=METRIC)
    upstream_label: str = Field(default="upstream", pattern=IDENTIFIER)
    memory_bytes: str = Field(default="process_resident_memory_bytes", pattern=METRIC)
    cpu_seconds_total: str = Field(default="process_cpu_seconds_total", pattern=METRIC)


class PrometheusConfig(BaseModel):
    url: str = "http://localhost:9090"
    username: str | None = None
    password: SecretStr | None = None
    bearer_token: SecretStr | None = None
    query_timeout: str = Field(default="10s", pattern=r"^\d+[smh]$")
    timeout_seconds: float = Field(default=15.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=6)


class MetricsIntegration(BaseModel):
    service_label: str = Field(default="service", pattern=IDENTIFIER)
    resource_service_label: str | None = Field(default=None, pattern=IDENTIFIER)
    names: MetricNames = Field(default_factory=MetricNames)
    allow_raw_promql: bool = True
    max_series: int = Field(default=50, ge=1, le=500)
    max_window_minutes: int = Field(default=1440, ge=1)
    max_points: int = Field(default=120, ge=10, le=1000)
    prometheus: PrometheusConfig = Field(default_factory=PrometheusConfig)


class GitHubConfig(BaseModel):
    api_url: str = "https://api.github.com"
    token: SecretStr | None = None
    timeout_seconds: float = Field(default=15.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=6)
    max_commits: int = Field(default=30, ge=1, le=100)
    max_files: int = Field(default=20, ge=1, le=100)
    max_patch_chars: int = Field(default=4000, ge=200)
    max_total_patch_chars: int = Field(default=20000, ge=1000)


class CodeIntegration(BaseModel):
    github: GitHubConfig = Field(default_factory=GitHubConfig)


class EmbeddingConfig(BaseModel):
    provider: Literal["ollama", "openai"] = "ollama"
    model: str = "nomic-embed-text"
    dimensions: int = Field(default=768, ge=8, le=4096)
    base_url: str | None = None
    api_key: SecretStr | None = None
    query_prefix: str = ""
    document_prefix: str = ""
    batch_size: int = Field(default=32, ge=1, le=512)
    timeout_seconds: float = Field(default=60.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=6)


class RunbooksIntegration(BaseModel):
    backend: Literal["pgvector", "keyword"] = "pgvector"
    directory: Path = Path("./runbooks")
    table_prefix: str = Field(default="runbook", pattern=IDENTIFIER)
    max_chunk_chars: int = Field(default=1500, ge=200, le=8000)
    max_results: int = Field(default=5, ge=1, le=20)
    embeddings: EmbeddingConfig = Field(default_factory=EmbeddingConfig)


class IntegrationsConfig(BaseModel):
    logs: LogsIntegration = Field(default_factory=LogsIntegration)
    metrics: MetricsIntegration = Field(default_factory=MetricsIntegration)
    code: CodeIntegration = Field(default_factory=CodeIntegration)
    runbooks: RunbooksIntegration = Field(default_factory=RunbooksIntegration)


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

    def service(self, name: str) -> ServiceConfig | None:
        return next((s for s in self.services if s.name == name), None)

    @property
    def service_names(self) -> set[str]:
        """An empty services list means no fix can target anything: the safe default."""
        return {s.name for s in self.services}


settings = Settings()
