import hashlib
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from fastapi import BackgroundTasks, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from .config import settings
from .graph import build_graph
from .state import Alert
from .telemetry import (
    APPROVALS,
    INCIDENT_ERRORS,
    INCIDENTS,
    INCIDENTS_ACTIVE,
    INVESTIGATION_SECONDS,
    incident_id_var,
    setup_logging,
)

setup_logging()
log = logging.getLogger("copilot")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_url = settings.postgres_url.get_secret_value()
    async with AsyncPostgresSaver.from_conn_string(db_url) as saver:
        await saver.setup()
        app.state.graph = build_graph(checkpointer=saver)
        log.info(
            "copilot started",
            extra={
                "fields": {
                    "environment": settings.environment,
                    "services": sorted(settings.service_names),
                    "dry_run": settings.guardrails.dry_run,
                }
            },
        )
        yield


app = FastAPI(title="incident-copilot", lifespan=lifespan)


def _config(incident_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": incident_id}}


async def _run(incident_id: str, alert: Alert) -> None:
    token = incident_id_var.set(incident_id)
    INCIDENTS_ACTIVE.inc()
    started = time.perf_counter()
    try:
        log.info(
            "investigation started",
            extra={"fields": {"alert": alert.name, "service": alert.service}},
        )
        await app.state.graph.ainvoke(
            {"incident_id": incident_id, "alert": alert}, _config(incident_id)
        )
        INVESTIGATION_SECONDS.observe(time.perf_counter() - started)
        log.info("investigation finished, awaiting decision")
    except Exception:
        INCIDENT_ERRORS.labels("investigation").inc()
        log.exception("investigation failed")
    finally:
        INCIDENTS_ACTIVE.dec()
        incident_id_var.reset(token)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> JSONResponse:
    try:
        async with await psycopg.AsyncConnection.connect(
            settings.postgres_url.get_secret_value(), connect_timeout=2
        ) as conn:
            await conn.execute("SELECT 1")
    except Exception as exc:
        return JSONResponse(
            {"status": "unavailable", "postgres": type(exc).__name__}, status_code=503
        )
    return JSONResponse({"status": "ready"})


@app.get("/metrics")
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/alerts")
async def receive_alertmanager(
    payload: dict[str, Any], background: BackgroundTasks
) -> dict[str, list[str]]:
    started = []
    for a in payload.get("alerts", []):
        if a.get("status") != "firing":
            continue
        labels = a.get("labels", {})
        service = labels.get("service") or labels.get("instance", "unknown").split(":")[0]
        alert = Alert(
            name=labels.get("alertname", "unknown"),
            service=service,
            severity=labels.get("severity", "page"),
            summary=a.get("annotations", {}).get("summary", ""),
            labels=labels,
            starts_at=a.get("startsAt", ""),
        )
        fingerprint = a.get("fingerprint") or alert.model_dump_json()
        incident_id = hashlib.sha1(fingerprint.encode()).hexdigest()[:12]
        INCIDENTS.labels(alert.name).inc()
        background.add_task(_run, incident_id, alert)
        started.append(incident_id)
    return {"incidents": started}


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: str) -> dict[str, Any]:
    snap = await app.state.graph.aget_state(_config(incident_id))
    if not snap.values:
        raise HTTPException(404, "unknown incident")
    return {
        "state": snap.values,
        "waiting_on": list(snap.next),
        "interrupts": [i.value for t in snap.tasks for i in t.interrupts],
    }


class Decision(BaseModel):
    approved: bool
    reviewer: str
    note: str = ""


@app.post("/incidents/{incident_id}/decision")
async def decide(incident_id: str, decision: Decision) -> dict[str, Any]:
    snap = await app.state.graph.aget_state(_config(incident_id))
    if "approval" not in snap.next:
        raise HTTPException(409, "incident is not waiting for approval")
    token = incident_id_var.set(incident_id)
    try:
        result = await app.state.graph.ainvoke(
            Command(resume=decision.model_dump()), _config(incident_id)
        )
    except Exception as exc:
        INCIDENT_ERRORS.labels("execution").inc()
        log.exception("resume after decision failed")
        raise HTTPException(500, "failed to apply decision") from exc
    finally:
        incident_id_var.reset(token)
    outcome = result.get("approval", "unknown")
    APPROVALS.labels(outcome).inc()
    log.info(
        "decision applied",
        extra={
            "fields": {
                "reviewer": decision.reviewer,
                "outcome": outcome,
                "execution_result": result.get("execution_result"),
            }
        },
    )
    return {"approval": outcome, "execution_result": result.get("execution_result")}
