#!/bin/bash

echo "Starting all services..."

# Start AI Service
uv run ai-service &
AI_PID=$!

# Start Backend Service
uv run backend-service &
BACKEND_PID=$!

# Start Agent Service
uv run agent-service --vertex &
AGENT_PID=$!

# Start API Gateway
docker-compose -f docker-compose.gateway.yml up -d

echo "All services started!"
echo "Press Ctrl+C to stop all Python services."

# Wait for all background processes
wait $AI_PID $BACKEND_PID $AGENT_PID
