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

