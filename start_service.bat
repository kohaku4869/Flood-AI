@echo off
echo Starting all services...

start "AI Service" cmd /k "uv run ai-service"
start "Backend Service" cmd /k "uv run backend-service"
start "Agent Service" cmd /k "uv run agent-service"

echo All services started!
