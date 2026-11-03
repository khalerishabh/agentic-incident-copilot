# Agentic Incident Copilot (LangGraph + MCP)

An on-call assistant. An alert fires, a supervisor agent fans out to log, metrics and code
agents, they gather evidence through MCP servers, an RCA writer drafts a root cause and a fix,
and a human must approve before anything runs.

## Layout

```
fakeapp/                 microservices we break on purpose
  common/                JSON logging, Prometheus metrics, chaos (fault injection)
  services/              gateway, orders, payments, inventory
  inject.py              CLI to enable/disable faults
  loadgen.py             steady background traffic
src/mcp_servers/         read-only MCP servers (FastMCP, streamable HTTP)
  logs/      :9101       error_summary, search_logs, trace_request
  metrics/   :9102       service_red, resource_usage, upstream_errors, run_promql
  github/    :9103       recent_commits, commit_diff
  runbook/   :9104       search_runbooks, get_runbook (keyword v0, pgvector later)
src/copilot/             the LangGraph agent
  state.py               typed state (Alert, Evidence, RootCause, ProposedFix)
  graph.py               supervisor -> investigators -> rca_writer -> approval -> executor
  nodes/approval.py      guardrails + interrupt() for human-in-the-loop
  guardrails.py          allow-list for write actions
  budget.py              per-incident token budget
  api.py                 FastAPI: /alerts webhook, /incidents/{id}, /incidents/{id}/decision
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
python -m fakeapp.inject enable payments error_rate --param probability=0.4
# watch http://localhost:9090/alerts, then:
python -m fakeapp.inject disable payments error_rate
```

Run the MCP servers and the copilot API locally (one terminal each):

```powershell
$env:LOG_DIR="./data/logs"; python -m mcp_servers.logs.server
python -m mcp_servers.metrics.server
python -m mcp_servers.github.server
python -m mcp_servers.runbook.server
uvicorn copilot.api:app --app-dir src --port 8080
```

Alertmanager posts to `host.docker.internal:8080/alerts`, so the API on your machine receives alerts.

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

1. Week 1: fake app + fault injector (add DB pool exhaustion, slow query, bad config, bad commit)
2. Week 2: MCP servers hardened, runbook RAG on pgvector
3. Week 3: single-agent baseline over the same tools
4. Week 4: real supervisor + investigators + RCA writer with structured output
5. Week 5: Langfuse tracing, eval harness over 20-30 incidents, N repeats each
6. Week 6: results report, demo video


