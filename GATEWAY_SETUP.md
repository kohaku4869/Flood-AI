# API Gateway Setup

This project uses an **Nginx API Gateway** running in a lightweight Docker container to route traffic from clients (like the Android App and Web Frontend) to the three separate backend Python microservices.

## Architecture & Ports

The API Gateway listens on **Port 8080** on your local machine.

It forwards requests based on path prefixes:
1. `/api/backend/*` ---> Forwarded to **Backend Service** (running on port `5000`)
2. `/api/ai/*` ---> Forwarded to **AI Service** (running on port `8000`)
3. `/api/agent/*` ---> Forwarded to **Agent Service** (running on port `8001`)

*Note: The gateway automatically strips the `/api/...` prefix when forwarding to the service. For example, a request to `http://localhost:8080/api/ai/api/v1/predict` becomes `http://localhost:8000/api/v1/predict`.*

## CORS
CORS is explicitly handled by the Nginx configuration. It will automatically attach the following headers to **all** endpoints:
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods`
- `Access-Control-Allow-Headers`
This ensures seamless requests from `localhost`, your Android phone, or any cross-origin web client. We also handle WebSocket connections properly (e.g., for the Agent Service).

## Prerequisites
- **Docker**: You must have Docker installed and running on your device.
- **Docker Compose**: Ensures you can run the `docker-compose.gateway.yml` file.

## Running the Gateway

### using the Startup Scripts
The easiest way is to use the provided startup scripts. These scripts start your Python microservices and also start the API Gateway using Docker.

**On Windows:**
```cmd
start_service.bat
```

**On Linux / macOS:**
```bash
chmod +x start_service.sh
./start_service.sh
```

### Manually Starting the Gateway only
If you prefer to start only the gateway, use the Docker Compose file:
```bash
docker-compose -f docker-compose.gateway.yml up -d
```
You can view the logs or stop the gateway via Docker Desktop, or using the CLI:
```bash
# Stop the API Gateway
docker-compose -f docker-compose.gateway.yml down
```
