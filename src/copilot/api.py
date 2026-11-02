import hashlib
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.types import Command
from pydantic import BaseModel

from .config import settings
from .graph import build_graph
from .state import Alert


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncPostgresSaver.from_conn_string(settings.postgres_url) as saver:
        await saver.setup()
        app.state.graph = build_graph(checkpointer=saver)
        yield


app = FastAPI(title="incident-copilot", lifespan=lifespan)


def _config(incident_id: str) -> dict:
    return {"configurable": {"thread_id": incident_id}}


async def _run(incident_id: str, alert: Alert) -> None:
    await app.state.graph.ainvoke({"incident_id": incident_id, "alert": alert}, _config(incident_id))


@app.post("/alerts")
async def receive_alertmanager(payload: dict, background: BackgroundTasks):
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
        incident_id = hashlib.sha1(a.get("fingerprint", alert.model_dump_json()).encode()).hexdigest()[:12]
        background.add_task(_run, incident_id, alert)
        started.append(incident_id)
    return {"incidents": started}


@app.get("/incidents/{incident_id}")
async def get_incident(incident_id: str):
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
async def decide(incident_id: str, decision: Decision):
    snap = await app.state.graph.aget_state(_config(incident_id))
    if "approval" not in snap.next:
        raise HTTPException(409, "incident is not waiting for approval")
    result = await app.state.graph.ainvoke(Command(resume=decision.model_dump()), _config(incident_id))
    return {"approval": result.get("approval"), "execution_result": result.get("execution_result")}
