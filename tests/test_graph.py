from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from copilot.graph import build_graph
from copilot.state import Alert


async def test_graph_pauses_for_approval_then_executes():
    graph = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t1"}}
    alert = Alert(name="HighErrorRate", service="payments")

    await graph.ainvoke({"incident_id": "t1", "alert": alert}, cfg)
    snap = await graph.aget_state(cfg)
    assert snap.next == ("approval",)
    assert len(snap.values["evidence"]) == 3

    result = await graph.ainvoke(Command(resume={"approved": True}), cfg)
    assert result["approval"] == "approved"
    assert result["execution_result"].startswith("DRY RUN")


async def test_rejection_skips_executor():
    graph = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": "t2"}}
    await graph.ainvoke({"incident_id": "t2", "alert": Alert(name="x", service="orders")}, cfg)
    result = await graph.ainvoke(Command(resume={"approved": False}), cfg)
    assert result["approval"] == "rejected"
    assert "execution_result" not in result
