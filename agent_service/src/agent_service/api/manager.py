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

    async def show_camera_image(self, camera_id: str, street_name: str):
        for connection in self.active_connections:
            await connection.send_json({"type": "show_camera_image", "camera_id": camera_id, "street_name": street_name})

manager = ConnectionManager()
