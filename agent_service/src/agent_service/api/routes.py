import json
from fastapi import APIRouter, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from agent_service.api.manager import manager
from agent_service.core.graph.graph_builder import graph
from agent_service.core.graph.state import AgentState

router = APIRouter()

# ── In-memory state ──────────────────────────────────────────────────────────

_current_state: dict = {"messages": []}


def _get_state() -> dict:
    return _current_state


def _reset_state():
    global _current_state
    _current_state = {"messages": []}


# ── Request models ───────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Stream chat response qua SSE.
    Dùng graph.astream(stream_mode="updates") thay vì astream_events
    để tránh bug 'ClientResponse' trong langchain-google-genai async.
    """
    state = _get_state()
    state["messages"].append(HumanMessage(content=request.message))

    async def event_generator():
        try:
            last_ai_content = None

            async for node_output in graph.astream(
                state,
                stream_mode="updates",
            ):
                for node_name, output in node_output.items():
                    messages = output.get("messages", [])

                    if node_name == "agent":
                        for msg in messages:
                            # Phát hiện tool calls
                            if isinstance(msg, AIMessage) and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    yield f"data: {json.dumps({'type': 'tool_call', 'name': tc.get('name', '')}, ensure_ascii=False)}\n\n"

                            # Nội dung text từ AI
                            if msg.content:
                                last_ai_content = msg.content
                                yield f"data: {json.dumps({'type': 'token', 'content': msg.content}, ensure_ascii=False)}\n\n"

                    elif node_name == "tools":
                        for msg in messages:
                            if isinstance(msg, ToolMessage):
                                yield f"data: {json.dumps({'type': 'tool_result', 'name': msg.name, 'result': str(msg.content)[:500]}, ensure_ascii=False)}\n\n"

            # Cập nhật state: thêm AI response cuối cùng vào lịch sử
            if last_ai_content:
                _current_state["messages"].append(AIMessage(content=last_ai_content))

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/reset")
async def reset_state():
    """Reset agent state và xoá lịch sử chat."""
    _reset_state()
    return {"status": "ok", "message": "State đã được reset."}


@router.get("/history")
async def get_history():
    """Trả về lịch sử chat hiện tại."""
    state = _get_state()
    messages = []
    for msg in state.get("messages", []):
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})
    return {"messages": messages}


# ── WebSocket cho frontend map ───────────────────────────────────────────────

@router.websocket("/ws/frontend")
async def websocket_frontend(websocket: WebSocket):
    """WebSocket endpoint để gửi lệnh tới frontend map."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_json()
    except Exception:
        await manager.disconnect(websocket)