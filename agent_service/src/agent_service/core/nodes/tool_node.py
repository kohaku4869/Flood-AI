import json
from langchain_core.messages import ToolMessage, AIMessage

from agent_service.core.graph.state import AgentState
from agent_service.core.tools.flood_tool import TOOL_MAP


async def tool_node(state: AgentState) -> dict:
    """
    Custom tool executor node.
    Nhận AIMessage chứa tool_calls, thực thi từng tool và trả về ToolMessage.
    """
    last_message: AIMessage = state.messages[-1]
    tool_messages = []
    state_updates: dict = {}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_call_id = tool_call["id"]

        tool = TOOL_MAP.get(tool_name)

        if tool is None:
            result = f"Tool '{tool_name}' không tồn tại."
        else:
            try:
                result = await tool.ainvoke(tool_args)

                # Cập nhật state tuỳ theo tool
                if tool_name == "get_camera_status":
                    street = tool_args.get("street_name")
                    cache = state.camera_status_cache or {}
                    cache[street] = result
                    state_updates["camera_status_cache"] = cache
                    state_updates["queried_street"] = street

                elif tool_name == "get_camera_future_status":
                    state_updates["queried_street"] = tool_args.get("street_name")
                    state_updates["selected_time_delta"] = tool_args.get("time_delta")

                elif tool_name == "get_current_condition":
                    state_updates["current_condition"] = result

                elif tool_name == "set_route":
                    state_updates["route_start"] = tool_args.get("start_coords")
                    state_updates["route_end"] = tool_args.get("end_coords")
                    state_updates["route_status"] = "sent"

            except Exception as e:
                result = f"Lỗi khi chạy tool '{tool_name}': {str(e)}"
                state_updates["error"] = str(e)

                if tool_name == "set_route":
                    state_updates["route_status"] = "error"

        tool_messages.append(
            ToolMessage(
                content=json.dumps(result, ensure_ascii=False),
                tool_call_id=tool_call_id,
                name=tool_name,
            )
        )

    return {"messages": tool_messages, **state_updates}
