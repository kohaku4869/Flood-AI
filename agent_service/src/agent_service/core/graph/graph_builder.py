from langgraph.graph import StateGraph, END
from langchain_core.messages import AIMessage

from agent_service.core.graph.state import AgentState
from agent_service.core.nodes.agent_node import agent_node
from agent_service.core.nodes.tool_node import tool_node


def should_continue(state: AgentState) -> str:
    """Quyết định sau agent_node đi đâu tiếp."""
    last = state.messages[-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return END


def build_graph():
    """Build và compile LangGraph agent."""
    builder = StateGraph(AgentState)

    # Thêm nodes
    builder.add_node("agent", agent_node)
    builder.add_node("tools", tool_node)

    # Entry point
    builder.set_entry_point("agent")

    # Edges
    builder.add_conditional_edges("agent", should_continue)
    builder.add_edge("tools", "agent")

    return builder.compile()


# Graph instance sẵn sàng dùng
graph = build_graph()
