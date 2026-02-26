from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    
    async def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
    
    async def set_route_and_find(self, start: dict, end: dict):
        for connection in self.active_connections:
            await connection.send_json({"type": "set_route_and_find", "start": start, "end": end})

manager = ConnectionManager()
