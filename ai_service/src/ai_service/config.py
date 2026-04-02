"""
Configuration module for AI Service.

This module contains all configuration settings, constants, and paths
for the flood image classification service.
"""

import os
from pathlib import Path
from typing import Dict, List

# ============================================================================
# Path Configuration (Absolute Paths)
# ============================================================================

# Get the absolute path to this file's directory
BASE_DIR = Path(__file__).resolve().parent

# Model directory and file paths
MODELS_DIR = BASE_DIR / "models"
MODEL_DIR = MODELS_DIR  # backward-compat alias
MODEL_PATH = MODELS_DIR / "flood_model_final.onnx"
MODEL_DATA_PATH = MODELS_DIR / "flood_model_final.onnx.data"

# YOLO Severity Model (flood segmentation, 1 class: flood)
# Export with: yolo export model=best.pt format=onnx imgsz=640 simplify=True
# Place the exported file here:
YOLO_SEVERITY_MODEL_PATH = MODELS_DIR / "yolo_flood_seg.onnx"

# data.yaml class mapping  →  nc: 1, names: ['flood']
YOLO_FLOOD_CLASS_ID: int = 0  # class index for "flood"


# ============================================================================
# Model Configuration
# ============================================================================

# Class labels mapping
CLASS_LABELS: Dict[int, str] = {
    0: "dry_road",
    1: "flood"
}

# Confidence threshold for predictions
CONFIDENCE_THRESHOLD: float = 0.7

# Input image size for the model
IMAGE_SIZE: tuple = (224, 224)

# Expected input shape (batch_size, channels, height, width)
INPUT_SHAPE: tuple = (1, 3, 224, 224)


# ============================================================================
# Image Preprocessing Configuration
# ============================================================================

# ImageNet normalization parameters
# These are the standard mean and std values used for ImageNet pre-trained models
IMAGENET_MEAN: List[float] = [0.485, 0.456, 0.406]
IMAGENET_STD: List[float] = [0.229, 0.224, 0.225]


# ============================================================================
# Application Configuration
# ============================================================================

class AppConfig:
    """Application configuration."""
    
    # Server settings
    HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("APP_PORT", "8000"))
    DEBUG: bool = os.getenv("APP_DEBUG", "False").lower() in ("true", "1", "yes")
    
    # Worker settings
    import multiprocessing
    # Default to CPU count, but allow override via env var
    WORKERS: int = int(os.getenv("APP_WORKERS", multiprocessing.cpu_count()))
    
    # File upload settings
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024  # 16 MB max file size
    ALLOWED_EXTENSIONS: set = {"png", "jpg", "jpeg", "bmp", "gif"}
    
    # API settings
    API_VERSION: str = "v1"
    API_PREFIX: str = f"/api/{API_VERSION}"


# ============================================================================
# Logging Configuration
# ============================================================================

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"]
    }
}
