"""
API routes for the flood classification service using FastAPI.

This module defines FastAPI routers and endpoints for the AI service.
"""

import base64
import io
from typing import Dict, Any, Optional

import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from pydantic import BaseModel
import logging

from ai_service.config import AppConfig
from ai_service.core import FloodClassifier
from ai_service.core.flood_severity import FloodSeverityEstimator, SeverityConfig
from ai_service.utils import preprocess_image, validate_image_file

logger = logging.getLogger(__name__)

# Create routers
router = APIRouter()
health_router = APIRouter()

# Initialize model (singleton - loaded once when module is imported)
try:
    classifier = FloodClassifier()
    logger.info("Model initialized successfully in routes module")
except Exception as e:
    logger.error(f"Failed to initialize model: {e}")
    classifier = None


# ============================================================================
# Pydantic Models
# ============================================================================

class PredictionResult(BaseModel):
    """Prediction result structure."""
    class_name: str
    class_id: int
    confidence: float
    confident: bool
    threshold: float
    probabilities: Dict[str, float]


class PredictResponse(BaseModel):
    """Response for prediction endpoint."""
    success: bool
    prediction: PredictionResult = None
    error: str = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str
    model: Dict[str, Any]


# ============================================================================
# Routes
# ============================================================================

@router.post("/predict")
async def predict(file: UploadFile = File(...)):
    """
    Image classification endpoint.
    
    Accepts an image file via multipart/form-data and returns classification results.
    
    Request:
        POST /api/v1/predict
        Content-Type: multipart/form-data
        Body: file=<image_file>
    
    Response:
        {
            "success": true,
            "prediction": {
                "class": "flood",
                "class_id": 1,
                "confidence": 0.87,
                "confident": true,
                "threshold": 0.7,
                "probabilities": {
                    "dry_road": 0.13,
                    "flood": 0.87
                }
            }
        }
    """
    # Check if model is loaded
    if classifier is None:
        logger.error("Model not initialized")
        raise HTTPException(
            status_code=500,
            detail="Model not initialized. Please check server logs."
        )
    
    # Check if filename is empty
    if not file.filename:
        logger.warning("Empty filename in request")
        raise HTTPException(
            status_code=400,
            detail="No file selected. Please select an image file."
        )
    
    # Validate file extension
    if not validate_image_file(file.filename, AppConfig.ALLOWED_EXTENSIONS):
        logger.warning(f"Invalid file type: {file.filename}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(AppConfig.ALLOWED_EXTENSIONS)}"
        )
    
    try:
        logger.info(f"Processing image: {file.filename}")
        
        # Read file content
        content = await file.read()
        
        # Preprocess the image
        from io import BytesIO
        preprocessed = preprocess_image(BytesIO(content))
        
        # Run prediction
        result = classifier.predict(preprocessed)
        
        # Build response
        response = {
            "success": True,
            "prediction": {
                "class": result["predicted_label"],
                "class_id": result["predicted_class"],
                "confidence": round(result["confidence"], 4),
                "confident": result["confident"],
                "threshold": result["threshold"],
                "probabilities": {
                    label: round(prob, 4)
                    for label, prob in result["probabilities"].items()
                }
            }
        }
        
        logger.info(f"Prediction successful for {file.filename}: {result['predicted_label']}")
        
        return response
    
    except ValueError as e:
        # Image preprocessing errors
        logger.error(f"Image preprocessing error: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"Failed to process image: {str(e)}"
        )
    
    except Exception as e:
        # Unexpected errors
        logger.error(f"Unexpected error during prediction: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred. Please try again."
        )


@health_router.get("/health")
async def health_check():
    """
    Health check endpoint.
    
    Returns the service status and model information.
    """
    model_loaded = classifier is not None
    
    response = {
        "status": "healthy" if model_loaded else "degraded",
        "service": "flood-classification-ai",
        "version": AppConfig.API_VERSION,
        "model": {
            "loaded": model_loaded
        }
    }
    
    # Add model info if available
    if model_loaded:
        try:
            response["model"]["info"] = classifier.get_model_info()
        except Exception as e:
            logger.error(f"Failed to get model info: {e}")
            response["model"]["info_error"] = str(e)
    
    if not model_loaded:
        raise HTTPException(status_code=503, detail=response)
    
    return response


# Singleton severity estimator (default config, lazy-init OK since it has no heavy model)
_severity_estimator: Optional[FloodSeverityEstimator] = None


def _get_severity_estimator(
    roi: float = 0.5,
    low: float = 0.08,
    medium: float = 0.25,
    high: float = 0.50,
) -> FloodSeverityEstimator:
    """Return a (re)configured estimator. Cheap to construct – no model load."""
    cfg = SeverityConfig(
        roi_bottom_fraction=roi,
        low_threshold=low,
        medium_threshold=medium,
        high_threshold=high,
    )
    return FloodSeverityEstimator(cfg)


def _decode_image(raw: bytes) -> np.ndarray:
    """Decode raw image bytes to BGR ndarray via OpenCV."""
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Cannot decode image bytes.")
    return img


def _mask_to_b64(mask: np.ndarray) -> str:
    """Encode a binary (0/255) mask as a base64 PNG string."""
    # Convert to RGBA: blue tint for water, transparent elsewhere
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    water = mask > 0
    rgba[water] = [30, 144, 255, 160]   # dodger-blue, semi-transparent
    ok, buf = cv2.imencode(".png", rgba)
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


@router.post("/analyze-severity")
async def analyze_severity(
    file: UploadFile = File(...),
    roi: float = Query(0.5, ge=0.1, le=0.9, description="Bottom ROI fraction"),
    low: float = Query(0.08,  ge=0.0, le=1.0, description="Low severity threshold"),
    medium: float = Query(0.25, ge=0.0, le=1.0, description="Medium severity threshold"),
    high: float = Query(0.50,  ge=0.0, le=1.0, description="High severity threshold"),
):
    """
    Heuristic flood severity estimation endpoint.

    Accepts an image file and returns:
    - severity     : "None" | "Low" | "Medium" | "High"
    - coverage_ratio  : boosted water coverage (0–1)
    - raw_coverage    : coverage before wheel boost
    - wheels_detected : number of wheel-like circles near water
    - mask_b64        : base64-encoded RGBA PNG of the water mask overlay
    """
    if not validate_image_file(file.filename, AppConfig.ALLOWED_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(AppConfig.ALLOWED_EXTENSIONS)}",
        )

    try:
        raw = await file.read()
        img = _decode_image(raw)

        estimator = _get_severity_estimator(roi, low, medium, high)
        result = estimator.estimate(img)

        mask_b64 = _mask_to_b64(result.water_mask)

        return {
            "success": True,
            "severity": result.severity,
            "coverage_ratio": round(result.coverage_ratio, 4),
            "raw_coverage": round(result.raw_coverage_ratio, 4),
            "wheels_detected": result.wheels_detected,
            "mask_b64": mask_b64,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"analyze-severity error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Severity analysis failed.")
