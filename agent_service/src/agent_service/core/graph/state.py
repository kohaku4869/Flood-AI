from pydantic import BaseModel
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing import Annotated, Optional,Dict


class AgentState(BaseModel):
    messages: Annotated[list[BaseMessage], add_messages]

    # Camera info
    queried_street: Optional[str] = None
    selected_time_delta: Optional[int] = 0
    camera_status_cache: Optional[dict[str, dict]] = None       # {street_name: result}

    # Weather
    current_condition: Optional[dict[str, float]] = None  # {tide: ..., rain: ...}

    # Routing
    route_start: Optional[dict[str, float]] = None        # {"lat": ..., "lng": ...}
    route_end: Optional[dict[str, float]] = None          # {"lat": ..., "lng": ...}
    route_status: Optional[str] = None

    # Control
    error: Optional[str] = None