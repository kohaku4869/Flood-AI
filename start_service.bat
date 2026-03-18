@echo off
echo Starting all services...

start "AI Service" cmd /k "uv run ai-service"
start "Backend Service" cmd /k "uv run backend-service"
start "Agent Service" cmd /k "uv run agent-service --vertex"
start "API Gateway" cmd /k "docker-compose -f docker-compose.gateway.yml up -d"

echo All services started!
