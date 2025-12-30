"""
Configuration module for backend service.
Loads settings from environment variables with sensible defaults.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from multiple possible locations
# Priority: 1) Project root, 2) backend_service folder, 3) Current dir
project_root = Path(__file__).parent.parent.parent.parent  # Go up from config.py to project root
env_paths = [
    project_root / ".env",  # d:/lap_trinh/python/flood-ai/.env
    project_root / "backend_service" / ".env",  # d:/lap_trinh/python/flood-ai/backend_service/.env
    Path(".env")  # Current directory
]

# Load first .env file found
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path)
        break

# AI Service Configuration
AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8000/api/v1/predict")
AI_SERVICE_TIMEOUT = int(os.getenv("AI_SERVICE_TIMEOUT", "30"))
AI_SERVICE_MAX_RETRIES = int(os.getenv("AI_SERVICE_MAX_RETRIES", "2"))

# OpenRouteService Routing Configuration (supports avoid_polygons in free tier)
OPENROUTE_API_KEY = os.getenv("OPENROUTE_API_KEY", "")
# Standard directions endpoint - returns JSON with routes array
OPENROUTE_BASE_URL = os.getenv("OPENROUTE_BASE_URL", "https://api.openrouteservice.org/v2/directions/driving-car")

# Camera Dataset Configuration
# CAMERA_DATASET_PATH = Path(os.getenv("CAMERA_DATASET_PATH", "dataset/dataset_camera_day_du.csv"))
CAMERA_DATASET_PATH = project_root / "dataset" / "dataset_camera_day_du.csv"

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "logs/backend_service.log")

# Camera Image Configuration
CAMERA_BASE_URL = os.getenv("CAMERA_BASE_URL", "https://giaothong.hochiminhcity.gov.vn:8007/Render/CameraHandler.ashx")
CAMERA_IMAGE_TIMEOUT = int(os.getenv("CAMERA_IMAGE_TIMEOUT", "10"))
INVALID_IMAGE_PATH = project_root / "assets" / "invalid_image.jpg"

# Ensure directories exist
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

# Flood Check Configuration
FLOOD_CHECK_INTERVAL_MINUTES = int(os.getenv("FLOOD_CHECK_INTERVAL_MINUTES", "60"))
FLOOD_BLOCK_RADIUS_METERS = int(os.getenv("FLOOD_BLOCK_RADIUS_METERS", "150"))  # Radius to block around flooded cameras

# TomTom API Configuration
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
TOMTOM_TRAFFIC_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData"
TOMTOM_ROUTING_URL = "https://api.tomtom.com/routing/1/calculateRoute"
TOMTOM_TILE_URL = "https://api.tomtom.com/traffic/map/4/tile/flow"
TOMTOM_TIMEOUT = int(os.getenv("TOMTOM_TIMEOUT", "10"))

# Traffic Cache Configuration
TRAFFIC_CACHE_TTL_SECONDS = int(os.getenv("TRAFFIC_CACHE_TTL_SECONDS", "120"))  # 2 minutes
