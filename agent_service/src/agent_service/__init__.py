from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agent_service.api.routes import router

app = FastAPI(title="Flood AI Agent Service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
