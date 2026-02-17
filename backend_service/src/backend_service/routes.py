"""
API routes for backend service using FastAPI.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from .logger import logger
from .routing_service import get_safe_route
from .flood_state import get_flood_state_manager
from .scheduler import trigger_immediate_flood_check
from . import config  # Import config to access FLOOD_BLOCK_RADIUS_METERS

router = APIRouter()


# ============================================================================
# Pydantic Models
# ============================================================================

class LatLng(BaseModel):
    """Latitude and longitude coordinates."""
    lat: float = Field(..., description="Latitude")
    lng: float = Field(..., description="Longitude")


class RouteRequest(BaseModel):
    """Request body for route calculation."""
    start_coords: LatLng = Field(..., description="Starting coordinates")
    end_coords: LatLng = Field(..., description="Ending coordinates")
    # camera_ids is no longer used for flood checking (we use cached state)
    # but kept for backward compatibility
    camera_ids: List[str] = Field(default=[], description="Camera IDs (deprecated, ignored)")


class RouteResponse(BaseModel):
    """Response for route calculation."""
    status: str
    message: str
    data: dict


class FloodStatusResponse(BaseModel):
    """Response for flood status endpoint."""
    test_mode: bool
    total_cameras: int
    flooded_count: int
    cameras: List[dict]


class TestFloodResponse(BaseModel):
    """Response for test flood toggle."""
    test_mode: bool
    message: str
    flooded_count: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str


class WeatherData(BaseModel):
    """Weather data for a specific time."""
    rain_3h: float = Field(..., description="Rainfall in last/next 3 hours (mm)")
    rain_level: str = Field(..., description="Rain level label in Vietnamese")
    rain_color: str = Field(..., description="Color for rain level")
    tide: float = Field(..., description="Tide level (meters)")
    tide_level: str = Field(..., description="Tide level label in Vietnamese")
    tide_color: str = Field(..., description="Color for tide level")
    tide_delta: float = Field(default=0, description="Tide change from previous hour")
    timestamp: str = Field(..., description="Data timestamp")


class WeatherResponse(BaseModel):
    """Response for weather endpoint."""
    hour: int = Field(..., description="Hour offset (0=current, 1-12=future)")
    weather: WeatherData


# ============================================================================
# Routes
# ============================================================================

@router.post("/route_request", response_model=RouteResponse)
async def route_request(request: RouteRequest):
    """
    Handle routing requests with flood avoidance.
    
    Uses cached flood states from FloodStateManager instead of
    real-time AI checks for faster response.
    """
    try:
        logger.info(f"Route request from {request.start_coords} to {request.end_coords}")
        
        # Get flooded coordinates from cached state
        flood_manager = get_flood_state_manager()
        flooded_coords = flood_manager.get_flooded_coords()
        
        logger.info(f"Using {len(flooded_coords)} cached flooded locations")
        
        # Convert flooded_coords from Dict format to List format for GraphHopper API
        flooded_points = [[fc["lat"], fc["lng"]] for fc in flooded_coords] if flooded_coords else []
        
        # Calculate safe route using routing service
        logger.info("Calculating safe route with flood avoidance and traffic awareness")
        route_result = get_safe_route(
            start_point=[request.start_coords.lat, request.start_coords.lng],
            end_point=[request.end_coords.lat, request.end_coords.lng],
            flooded_points=flooded_points
        )
        
        # Extract route coordinates from result dict
        path_coords_list = route_result.get("route", [])
        
        # Convert response from List format back to Dict format for frontend
        path_coords = [{"lat": coord[0], "lng": coord[1]} for coord in path_coords_list]
        
        if not path_coords:
            logger.warning("No route found")
            raise HTTPException(
                status_code=404,
                detail="Unable to calculate route between the given points"
            )
        
        response_data = {
            "start": request.start_coords.model_dump(),
            "end": request.end_coords.model_dump(),
            "flooded_count": len(flooded_coords),
            "flooded_coords": flooded_coords,
            "block_radius_meters": config.FLOOD_BLOCK_RADIUS_METERS,
            "path": path_coords,
            "path_length": len(path_coords),
            "test_mode": flood_manager.test_mode,
            # Traffic metadata from TomTom
            "distance": route_result.get("distance", 0),
            "ors_duration": route_result.get("ors_duration", 0),
            "traffic_duration": route_result.get("traffic_duration"),
            "traffic_delay": route_result.get("traffic_delay", 0),
            "traffic_status": route_result.get("traffic_status", "unknown"),
            "traffic_sections": route_result.get("traffic_sections", [])
        }
        
        logger.info(f"Route calculated: {len(path_coords)} waypoints, {len(flooded_coords)} flooded areas")
        
        return RouteResponse(
            status="success",
            message="Route calculated",
            data=response_data
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in route_request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/flood-status", response_model=FloodStatusResponse)
async def get_flood_status():
    """
    Get current flood status for all cameras.
    
    Returns the status of all cameras including whether they are flooded,
    their coordinates, and last check time.
    """
    flood_manager = get_flood_state_manager()
    
    return FloodStatusResponse(
        test_mode=flood_manager.test_mode,
        total_cameras=flood_manager.get_total_count(),
        flooded_count=flood_manager.get_flooded_count(),
        cameras=flood_manager.get_all_states()
    )


@router.post("/test-flood/enable", response_model=TestFloodResponse)
async def enable_test_flood():
    """
    Enable test flood mode.
    
    Marks 40% of cameras as randomly flooded for testing purposes.
    The scheduled flood checks will be skipped while test mode is active.
    """
    flood_manager = get_flood_state_manager()
    flooded_count = flood_manager.enable_test_mode(flood_percentage=0.4)
    
    logger.info(f"Test flood mode enabled: {flooded_count} cameras marked as flooded")
    
    return TestFloodResponse(
        test_mode=True,
        message=f"Test mode enabled. {flooded_count} cameras marked as flooded.",
        flooded_count=flooded_count
    )


@router.post("/test-flood/disable", response_model=TestFloodResponse)
async def disable_test_flood():
    """
    Disable test flood mode.
    
    Returns to using real flood status from AI service.
    Triggers an immediate flood status check.
    """
    flood_manager = get_flood_state_manager()
    flood_manager.disable_test_mode()
    
    # Trigger immediate real check
    await trigger_immediate_flood_check()
    
    logger.info("Test flood mode disabled, real flood check triggered")
    
    return TestFloodResponse(
        test_mode=False,
        message="Test mode disabled. Using real flood status.",
        flooded_count=flood_manager.get_flooded_count()
    )


@router.post("/flood-check/trigger")
async def trigger_flood_check():
    """
    Manually trigger an immediate flood status check.
    
    Useful for forcing an update without waiting for the scheduled interval.
    """
    flood_manager = get_flood_state_manager()
    
    if flood_manager.test_mode:
        raise HTTPException(
            status_code=400,
            detail="Cannot trigger flood check while test mode is active"
        )
    
    await trigger_immediate_flood_check()
    
    return {
        "status": "success",
        "message": "Flood check triggered",
        "flooded_count": flood_manager.get_flooded_count()
    }


@router.get("/health", response_model=HealthResponse)
async def health():
    """Health check endpoint."""
    return HealthResponse(status="healthy")


@router.get("/camera/{camera_id}/image")
async def get_camera_image(camera_id: str):
    """
    Get camera image by ID.
    
    Fetches the camera snapshot from the external camera API and returns it.
    If camera returns invalid image, returns the placeholder invalid_image.jpg.
    """
    from fastapi.responses import Response
    from .get_image import create_session, get_image_by_id
    
    try:
        # Create session and fetch image (returns tuple: image_bytes, is_valid)
        session = create_session()
        image_result = get_image_by_id(session, camera_id)
        
        if image_result and image_result[0]:
            image_data, is_valid = image_result
            headers = {
                "Cache-Control": "public, max-age=30",  # Cache for 30 seconds
            }
            
            # Add header indicating validity
            if not is_valid:
                headers["X-Image-Valid"] = "false"
                logger.debug(f"Returning placeholder image for camera {camera_id}")
            
            return Response(
                content=image_data,
                media_type="image/jpeg",
                headers=headers
            )
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Camera image not available for camera {camera_id}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching camera image for {camera_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/traffic/tile/{z}/{x}/{y}")
async def get_traffic_tile(z: int, x: int, y: int, style: str = "relative"):
    """
    Proxy endpoint for TomTom traffic flow tiles.
    
    Args:
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
        style: Traffic style - 'relative' (default) or 'absolute'
        
    Returns:
        Traffic tile image (PNG)
    """
    from fastapi.responses import Response
    from . import tomtom_service
    import requests
    
    try:
        # Get tile URL from TomTom service
        tile_url = tomtom_service.get_traffic_tile_url(z, x, y, style)
        
        if not tile_url:
            raise HTTPException(
                status_code=503,
                detail="TomTom API key not configured"
            )
        
        # Add API key as query parameter
        tile_url_with_key = f"{tile_url}?key={config.TOMTOM_API_KEY}"
        
        # Fetch tile from TomTom
        response = requests.get(
            tile_url_with_key,
            timeout=config.TOMTOM_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"TomTom tile fetch failed ({response.status_code}): {response.text}")
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to fetch traffic tile"
            )
        
        # Return the tile image
        return Response(
            content=response.content,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=120",  # Cache for 2 minutes (TomTom updates every minute)
                "X-Traffic-Style": style
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching traffic tile {z}/{x}/{y}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Risk Prediction Endpoints for "Soi Ngập" Tab
# ============================================================================

class PredictionResponse(BaseModel):
    """Response for risk predictions."""
    hour: int
    cache_timestamp: Optional[str]
    total_cameras: int
    high_risk_count: int
    cameras: List[dict]


class PredictionSummaryResponse(BaseModel):
    """Response for prediction summary."""
    cache_timestamp: Optional[str]
    hours_available: List[int]
    summary: List[dict]


@router.get("/predictions/{hour}", response_model=PredictionResponse)
async def get_predictions(hour: int):
    """
    Get risk predictions for a specific hour ahead.
    
    Args:
        hour: Hours ahead (1-12)
        
    Returns:
        List of camera predictions with risk scores and colors
    """
    if hour < 1 or hour > 12:
        raise HTTPException(
            status_code=400,
            detail="Hour must be between 1 and 12"
        )
    
    from .scheduler import get_risk_runner
    
    risk_runner = get_risk_runner()
    predictions = risk_runner.get_cached_predictions(hour)
    
    # If no cached predictions, calculate on demand
    if not predictions:
        try:
            predictions = risk_runner.predict(time_context=hour)
        except Exception as e:
            logger.error(f"Failed to calculate predictions for hour {hour}: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # Format camera data for frontend
    camera_data = []
    for p in predictions:
        camera_data.append({
            "camera_id": p.get("CamId", p.get("id", "")),
            "name": p.get("Street_Name", p.get("street_name", "")),
            "lat": p.get("Latitude", p.get("coords", {}).get("lat", 0)),
            "lng": p.get("Longitude", p.get("coords", {}).get("lng", 0)),
            "risk": p.get("risk", 0),
            "risk_level": p.get("risk_level", "low"),
            "risk_color": p.get("risk_color", "#22c55e"),
            "coef": p.get("Coef", 0.3)
        })
    
    cache_timestamp = risk_runner.get_cache_timestamp()
    high_risk_count = sum(1 for c in camera_data if c["risk"] >= 0.5)
    
    return PredictionResponse(
        hour=hour,
        cache_timestamp=cache_timestamp.isoformat() if cache_timestamp else None,
        total_cameras=len(camera_data),
        high_risk_count=high_risk_count,
        cameras=camera_data
    )


@router.get("/predictions/summary", response_model=PredictionSummaryResponse)
async def get_predictions_summary():
    """
    Get summary of predictions for all hours (1-12).
    
    Returns count of high-risk cameras per hour.
    """
    from .scheduler import get_risk_runner
    
    risk_runner = get_risk_runner()
    cache_timestamp = risk_runner.get_cache_timestamp()
    
    summary = []
    hours_available = []
    
    for hour in range(1, 13):
        predictions = risk_runner.get_cached_predictions(hour)
        if predictions:
            hours_available.append(hour)
            high_risk = sum(1 for p in predictions if p.get("risk", 0) >= 0.5)
            medium_risk = sum(1 for p in predictions if 0.25 <= p.get("risk", 0) < 0.5)
            low_risk = len(predictions) - high_risk - medium_risk
            
            summary.append({
                "hour": hour,
                "total": len(predictions),
                "high_risk": high_risk,
                "medium_risk": medium_risk,
                "low_risk": low_risk
            })
    
    return PredictionSummaryResponse(
        cache_timestamp=cache_timestamp.isoformat() if cache_timestamp else None,
        hours_available=hours_available,
        summary=summary
    )


@router.post("/risk-job/trigger")
async def trigger_risk_job():
    """
    Manually trigger the hourly risk job.
    
    Updates coefficients from AI, calculates 1-12h predictions, and logs training data.
    """
    from .scheduler import trigger_immediate_risk_job
    
    try:
        await trigger_immediate_risk_job()
        
        from .scheduler import get_risk_runner
        risk_runner = get_risk_runner()
        cache_timestamp = risk_runner.get_cache_timestamp()
        
        return {
            "status": "success",
            "message": "Risk job completed",
            "cache_timestamp": cache_timestamp.isoformat() if cache_timestamp else None
        }
    except Exception as e:
        logger.error(f"Failed to trigger risk job: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Weather Endpoints
# ============================================================================

def get_rain_level(rain_3h: float) -> tuple[str, str]:
    """
    Get rain level label and color based on 3-hour rainfall.
    
    Returns:
        tuple of (label, color)
    """
    if rain_3h <= 0:
        return ("Không mưa", "#22c55e")  # Green
    elif rain_3h <= 6:
        return ("Mưa nhẹ", "#84cc16")    # Lime
    elif rain_3h <= 12:
        return ("Mưa vừa", "#eab308")    # Yellow
    elif rain_3h <= 25:
        return ("Mưa to", "#f97316")     # Orange
    else:
        return ("Mưa rất to", "#ef4444") # Red


def get_tide_level(tide: float) -> tuple[str, str]:
    """
    Get tide level label and color based on tide height.
    
    Returns:
        tuple of (label, color)
    """
    if tide < 1.0:
        return ("Thấp", "#22c55e")       # Green
    elif tide < 1.4:
        return ("Trung bình", "#eab308") # Yellow
    elif tide < 1.7:
        return ("Cao", "#f97316")        # Orange
    else:
        return ("Rất cao", "#ef4444")    # Red


@router.get("/weather/current", response_model=WeatherResponse)
async def get_current_weather():
    """
    Get current weather (rain and tide) data.
    
    Returns current rainfall and tide level with Vietnamese labels.
    """
    from .WeatherService import RainFetcher, TideFetcher
    from datetime import datetime, timezone
    
    try:
        # Initialize fetchers
        rain_fetcher = RainFetcher()
        tide_fetcher = TideFetcher(config.TIDE_DATA_PATH)
        
        # Fetch current data (hour 0)
        rain_data = rain_fetcher.fetch(time_context=0)
        tide_data = tide_fetcher.fetch(time_context=0)
        
        rain_3h = rain_data.get("total_rain_3h", 0)
        tide = tide_data.get("tide_now", 1.0)
        tide_delta = tide_data.get("tide_delta", 0)
        
        rain_level, rain_color = get_rain_level(rain_3h)
        tide_level, tide_color = get_tide_level(tide)
        
        return WeatherResponse(
            hour=0,
            weather=WeatherData(
                rain_3h=round(rain_3h, 2),
                rain_level=rain_level,
                rain_color=rain_color,
                tide=round(tide, 2),
                tide_level=tide_level,
                tide_color=tide_color,
                tide_delta=round(tide_delta, 2),
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        )
    except Exception as e:
        logger.error(f"Error fetching current weather: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/weather/{hour}", response_model=WeatherResponse)
async def get_future_weather(hour: int):
    """
    Get weather forecast for a specific hour ahead.
    
    Args:
        hour: Hours ahead (1-12)
        
    Returns:
        Weather data for the specified future hour.
    """
    if hour < 1 or hour > 12:
        raise HTTPException(
            status_code=400,
            detail="Hour must be between 1 and 12"
        )
    
    from .WeatherService import RainFetcher, TideFetcher
    from datetime import datetime, timezone
    
    try:
        # Initialize fetchers
        rain_fetcher = RainFetcher()
        tide_fetcher = TideFetcher(config.TIDE_DATA_PATH)
        
        # Fetch future data
        rain_data = rain_fetcher.fetch(time_context=hour)
        tide_data = tide_fetcher.fetch(time_context=hour)
        
        rain_3h = rain_data.get("total_rain_3h", 0)
        tide = tide_data.get("tide_now", 1.0)
        tide_delta = tide_data.get("tide_delta", 0)
        
        rain_level, rain_color = get_rain_level(rain_3h)
        tide_level, tide_color = get_tide_level(tide)
        
        return WeatherResponse(
            hour=hour,
            weather=WeatherData(
                rain_3h=round(rain_3h, 2),
                rain_level=rain_level,
                rain_color=rain_color,
                tide=round(tide, 2),
                tide_level=tide_level,
                tide_color=tide_color,
                tide_delta=round(tide_delta, 2),
                timestamp=datetime.now(timezone.utc).isoformat()
            )
        )
    except Exception as e:
        logger.error(f"Error fetching weather for hour {hour}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

