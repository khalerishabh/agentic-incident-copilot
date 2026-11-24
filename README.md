# Agentic Incident Copilot (LangGraph + MCP)

[![ci](https://github.com/khalerishabh/agentic-incident-copilot/actions/workflows/ci.yml/badge.svg)](https://github.com/khalerishabh/agentic-incident-copilot/actions/workflows/ci.yml)

An on-call assistant. An alert fires, a supervisor agent fans out to log, metrics and code
agents, they gather evidence through MCP servers, an RCA writer drafts a root cause and a fix,
and a human must approve before anything runs.

## Layout

```
demo/                    sandbox microservices we break on purpose (demos and tests)
  common/                JSON logging, Prometheus metrics, chaos (fault injection)
  services/              gateway, orders, payments, inventory
  inject.py              CLI to enable/disable faults
  loadgen.py             steady background traffic
src/mcp_servers/         read-only MCP servers (FastMCP, streamable HTTP)
  common/                retrying HTTP client, input validation, tool error handling
  logs/      :9101       list_services, error_summary, search_logs, trace_request
                         backends: Loki (default) or local files (dev only)
  metrics/   :9102       compare_services, service_red, red_timeline, resource_usage,
                         upstream_errors, run_promql (Prometheus HTTP API)
  github/    :9103       service_repos, recent_commits, commit_diff
  runbook/   :9104       search_runbooks, get_runbook (keyword v0, pgvector in M1 PR3)
src/copilot/             the LangGraph agent
  state.py               typed state (Alert, Evidence, RootCause, ProposedFix)
  graph.py               supervisor -> investigators -> rca_writer -> approval -> executor
  nodes/approval.py      guardrails + interrupt() for human-in-the-loop
  guardrails.py          allow-list for write actions
  budget.py              per-incident token budget
  api.py                 FastAPI: /alerts webhook, /incidents/{id}, /incidents/{id}/decision,
                         /healthz, /readyz, /metrics
  config.py              typed settings from copilot.yaml, overridable by COPILOT_* env vars
  telemetry.py           JSON logs tagged with incident_id, Prometheus counters
copilot.yaml             all non-secret configuration
infra/                   Prometheus scrape + alert rules, Alertmanager webhook
runbooks/                markdown runbooks for the RAG server
evals/                   incident catalog with ground truth, scoring, eval runner
tests/                   guardrail and graph tests
```

## Quick start (Windows, PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env

pytest                                   # graph + guardrail tests, no infra needed

docker compose up -d --build             # fake app, Prometheus, Alertmanager, Postgres
python -m demo.inject enable payments error_rate --param probability=0.4
# watch http://localhost:9090/alerts, then:
python -m demo.inject disable payments error_rate
```

Run the MCP servers and the copilot API locally (one terminal each):

```powershell
python -m mcp_servers.logs.server
python -m mcp_servers.metrics.server
python -m mcp_servers.github.server
python -m mcp_servers.runbook.server
uvicorn copilot.api:app --app-dir src --port 8080
```

Alertmanager posts to `host.docker.internal:8080/alerts`, so the API on your machine receives alerts.

## Configuration

Everything a team customises lives in `copilot.yaml`: the services the copilot may act on,
LLM provider and model, MCP server URLs, token budget, guardrails and executor backend.
Any value can be overridden with an environment variable such as `COPILOT_LLM__MODEL`.

Secrets never go in `copilot.yaml`. Keys named like `*_token`, `*_api_key`, `*_password`,
`*_secret` or `postgres_url` make startup fail on purpose. Put them in `.env` or the
environment instead (see `.env.example`).

An empty `services` list means no fix can target anything, so a misconfigured install is safe.

## Integrations

Each MCP server talks to one kind of system through a backend chosen in `copilot.yaml`.
Every backend call has a timeout and retries timeouts, connection errors, 429 and 502-504
with exponential backoff. Other errors fail fast. Failures reach the agent as readable tool
errors (for example `logs/loki: unavailable after 3 attempts (timed out) (temporary, retry later)`)
instead of crashing the run. Tool inputs such as service names and request ids are validated
before any query is built.

### Logs

| Backend | Use for | How it finds a service |
|---------|---------|------------------------|
| `loki`  | the demo stack and real installs | stream label set by `service_label` |
| `file`  | quick local runs only | `<directory>/<service>.log` |

Field names inside log lines are configurable under `integrations.logs.fields`, so any JSON
log schema works. Loki multi-tenancy (`tenant_id`) and basic auth are supported; the password
comes only from `COPILOT_INTEGRATIONS__LOGS__LOKI__PASSWORD`.

The demo stack runs Loki on `:3100` and Grafana Alloy on `:12345`. Alloy ships the stdout of
every container labelled `incident.copilot.logs: "true"` to Loki, with a `service` label taken
from the Compose service name. To ship your own services' logs, add that label to them.

### Metrics

Queries use the Prometheus HTTP API, so Prometheus, Mimir, Thanos and VictoriaMetrics all work.
Metric and label names live under `integrations.metrics.names`, so services instrumented
with other conventions (for example Spring's `http_server_requests_seconds_count` with a `code`
label) need only config changes. Two tools return hints rather than verdicts:

- `red_timeline` reports when error ratio and p95 first rose and stayed up, to line a problem
  up with deploys and log events.
- `upstream_errors` names `likely_origins`: failing callees whose own downstream calls are
  healthy. When payments fails, orders and gateway fail too; this points at payments.

`run_promql` is an escape hatch for the agent. Turn it off with `allow_raw_promql: false`.

### Code

Each service maps to a repository and the paths that hold its code (`services[].repo`,
`paths`, optional `branch`), so `recent_commits` returns only commits that touched that
service. `commit_diff` lists the service's own files first, skips lock files and binaries,
and caps patch size per file and per commit. Set `GITHUB_TOKEN` to a read-only token;
without one GitHub allows 60 requests an hour. `api_url` supports GitHub Enterprise Server.

Each MCP server also serves `/healthz` and `/readyz`; `/readyz` checks its backend.

## Operating the copilot

| Endpoint   | Purpose                                                  |
|------------|----------------------------------------------------------|
| `/healthz` | process is alive                                         |
| `/readyz`  | Postgres is reachable; returns 503 otherwise             |
| `/metrics` | `copilot_incidents_total`, `copilot_approvals_total`, `copilot_tool_call_failures_total`, `copilot_tokens_used_total`, investigation time |

Logs are JSON on stdout, one line per event, with `incident_id` on every line of an investigation.

## Development

```powershell
pip install -e ".[dev]" mypy types-PyYAML
ruff check .
ruff format .
mypy
pytest
```

CI runs the same checks plus a Docker image build on every push and pull request.

## Design rules worth defending

- Agents only ever get read-only MCP tools. Write actions live in the `executor` node,
  which is reachable only after `interrupt()` returns an approval. Safety is enforced by graph
  structure, not by prompting.
- Guardrails run twice: before showing a fix to a human, and again in the executor, because state
  can change between pause and resume.
- MCP servers return summaries and capped results, never raw log dumps, to protect the token budget.
- Faults are visible only through symptoms. Chaos endpoints are excluded from logs so the eval
  cannot leak the answer.

## Roadmap

Self-hosted product, targeting Docker Compose and Kubernetes, with approvals in Slack.

- M0 Foundations: config file, CI, health and metrics (done)
- M1 Pluggable integrations: Loki, Prometheus, GitHub, runbooks on pgvector
- M2 Real agents: LLM provider abstraction, token budgets, structured RCA, Langfuse tracing
- M3 Slack approval flow (Socket Mode), audit log
- M4 Docker and Kubernetes executors with dry-run, idempotency and post-fix verification
- M5 Alert deduplication, concurrency limits, restart recovery
- M6 One-command install, Helm chart, docs
- M7 Injected-incident regression suite in CI (starts with M2)

Later: web dashboard and mobile app for approvals.
