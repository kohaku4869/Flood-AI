import os
from pathlib import Path
from dotenv import load_dotenv

# Project root: flood-ai/
PROJECT_ROOT = Path(__file__).resolve().parents[5]

load_dotenv(PROJECT_ROOT / ".env")

BACKEND_URL = "http://localhost:5000"
DATASET_PATH = str(PROJECT_ROOT / "dataset" / "dataset_camera_30_zones.csv")
AGENT_URL = "http://localhost:8001"

GEMINI_API_KEYS = os.getenv("GEMINI_API_KEY", "").split(",")
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")

MAX_RETRIES = 1
DEFAULT_RETRY_DELAY = 15