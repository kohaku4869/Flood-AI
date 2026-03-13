import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Project root: flood-ai/
PROJECT_ROOT = Path(__file__).resolve().parents[5]

load_dotenv(PROJECT_ROOT / ".env")

BACKEND_URL = "http://localhost:5000"
DATASET_PATH = str(PROJECT_ROOT / "dataset" / "dataset_camera_30_zones.csv")
AGENT_URL = "http://localhost:8001"

GEMINI_API_KEYS = os.getenv("GEMINI_API_KEY", "").split(",")
VERTEX_API_KEY = os.getenv("VERTEX_API_KEY", "").split(",")
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "")
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0196211540")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")

MAX_RETRIES = 5
DEFAULT_RETRY_DELAY = 15

# Detect LLM type from command line
LLM_TYPE = "vertexai" if "--vertex" in sys.argv else "gemini"