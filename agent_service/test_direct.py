"""
Test truc tiep graph agent (khong qua API).
Chay: cd agent_service && uv run python test_direct.py
"""

import asyncio
import sys
from langchain_core.messages import HumanMessage

sys.stdout.reconfigure(encoding="utf-8")


async def test_direct():
    # Import sau khi module ready
    from agent_service.core.graph.graph_builder import graph

    print("=== Test Direct Agent Graph ===\n")

    state = {"messages": [HumanMessage(content="Duong Nguyen Huu Canh co bi ngap khong?")]}

    print(f"User: {state['messages'][0].content}\n")
    print("Running graph...\n")

    result = await graph.ainvoke(state)

    # In ket qua
    for msg in result["messages"]:
        role = msg.__class__.__name__
        content = getattr(msg, "content", "")
        tool_calls = getattr(msg, "tool_calls", [])

        if tool_calls:
            print(f"[{role}] Tool calls:")
            for tc in tool_calls:
                print(f"  -> {tc['name']}({tc['args']})")
        elif content:
            print(f"[{role}] {content[:300]}")
        print()

    print("=== Done ===")


if __name__ == "__main__":
    asyncio.run(test_direct())
