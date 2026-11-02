from langgraph.graph import END, START, StateGraph

from .nodes.approval import after_approval, approval_gate
from .nodes.executor import executor
from .nodes.investigators import code_agent, log_agent, metrics_agent
from .nodes.rca_writer import rca_writer
from .nodes.supervisor import route_to_investigators, supervisor
from .state import IncidentState

INVESTIGATORS = ["log_agent", "metrics_agent", "code_agent"]


def build_graph(checkpointer=None):
    g = StateGraph(IncidentState)
    g.add_node("supervisor", supervisor)
    g.add_node("log_agent", log_agent)
    g.add_node("metrics_agent", metrics_agent)
    g.add_node("code_agent", code_agent)
    g.add_node("rca_writer", rca_writer)
    g.add_node("approval", approval_gate)
    g.add_node("executor", executor)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route_to_investigators, INVESTIGATORS)
    for name in INVESTIGATORS:
        g.add_edge(name, "rca_writer")
    g.add_edge("rca_writer", "approval")
    g.add_conditional_edges("approval", after_approval, ["executor", END])
    g.add_edge("executor", END)
    return g.compile(checkpointer=checkpointer)
