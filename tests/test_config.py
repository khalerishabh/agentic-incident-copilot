from pathlib import Path

import pytest

from copilot.config import SecretsInConfigError, Settings
from copilot.guardrails import check_fix
from copilot.state import ProposedFix


def _load(path: Path) -> Settings:
    class _S(Settings):
        model_config = Settings.model_config | {"yaml_file": path, "env_file": None}

    return _S()


def test_repo_config_loads():
    cfg = _load(Path("copilot.yaml"))
    assert {"gateway", "orders", "payments", "inventory"} <= cfg.service_names
    assert cfg.guardrails.dry_run is True


def test_env_overrides_yaml(tmp_path, monkeypatch):
    path = tmp_path / "copilot.yaml"
    path.write_text("llm:\n  model: from-yaml\n")
    monkeypatch.setenv("COPILOT_LLM__MODEL", "from-env")
    assert _load(path).llm.model == "from-env"


def test_secret_in_yaml_is_rejected(tmp_path):
    path = tmp_path / "copilot.yaml"
    path.write_text("postgres_url: postgresql://u:p@db/x\n")
    with pytest.raises(SecretsInConfigError):
        _load(path)


def test_nested_secret_in_yaml_is_rejected(tmp_path):
    path = tmp_path / "copilot.yaml"
    path.write_text("llm:\n  api_key: sk-123\n")
    with pytest.raises(SecretsInConfigError):
        _load(path)


def test_budget_key_is_not_mistaken_for_secret(tmp_path):
    path = tmp_path / "copilot.yaml"
    path.write_text("budget:\n  tokens_per_incident: 1000\n")
    assert _load(path).budget.tokens_per_incident == 1000


def test_no_services_blocks_every_fix(tmp_path):
    path = tmp_path / "copilot.yaml"
    path.write_text("environment: test\n")
    cfg = _load(path)
    assert check_fix(ProposedFix(action="restart", target="orders"), cfg)


def test_disallowed_action_is_blocked(tmp_path):
    path = tmp_path / "copilot.yaml"
    path.write_text("services: [{name: orders}]\nguardrails:\n  allowed_actions: [restart]\n")
    cfg = _load(path)
    assert check_fix(ProposedFix(action="restart", target="orders"), cfg) == []
    assert check_fix(ProposedFix(action="scale", target="orders", params={"replicas": 2}), cfg)


def test_plain_variables_in_dotenv_reach_the_environment(tmp_path, monkeypatch):
    import os

    from dotenv import load_dotenv

    (tmp_path / ".env").write_text("GITHUB_TOKEN=from-dotenv\n")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    load_dotenv(tmp_path / ".env", override=False)
    assert os.environ["GITHUB_TOKEN"] == "from-dotenv"
    monkeypatch.setenv("GITHUB_TOKEN", "real-env-wins")
    load_dotenv(tmp_path / ".env", override=False)
    assert os.environ["GITHUB_TOKEN"] == "real-env-wins"


def test_nested_env_override_keeps_sibling_values_from_yaml(tmp_path, monkeypatch):
    path = tmp_path / "copilot.yaml"
    path.write_text(
        "integrations:\n  logs:\n    max_lines: 77\n    loki:\n"
        "      url: http://localhost:3100\n      line_format: logfmt\n"
    )
    monkeypatch.setenv("COPILOT_INTEGRATIONS__LOGS__LOKI__URL", "http://loki:3100")
    logs = _load(path).integrations.logs
    assert logs.loki.url == "http://loki:3100"
    assert logs.loki.line_format == "logfmt"
    assert logs.max_lines == 77
