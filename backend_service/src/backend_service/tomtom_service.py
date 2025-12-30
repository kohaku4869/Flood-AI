"""
TomTom Traffic and Routing API integration service.
Provides real-time traffic data and traffic-aware route calculations.
"""
import requests
import time
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from .logger import logger
from . import config


# Simple in-memory cache for traffic data
_traffic_cache: Dict[str, Tuple[float, any]] = {}


def _get_cached_data(cache_key: str) -> Optional[any]:
    """
    Get data from cache if not expired.
    
    Args:
        cache_key: Cache key
        
    Returns:
        Cached data or None if expired/not found
    """
    if cache_key in _traffic_cache:
        timestamp, data = _traffic_cache[cache_key]
        if time.time() - timestamp < config.TRAFFIC_CACHE_TTL_SECONDS:
            return data
        else:
            # Remove expired entry
            del _traffic_cache[cache_key]
    return None


def _set_cached_data(cache_key: str, data: any) -> None:
    """
    Store data in cache with current timestamp.
    
    Args:
        cache_key: Cache key
        data: Data to cache
    """
    _traffic_cache[cache_key] = (time.time(), data)


def get_traffic_tile_url(z: int, x: int, y: int, style: str = "relative") -> str:
    """
    Generate TomTom traffic flow tile URL.
    
    Args:
        z: Zoom level
        x: Tile X coordinate
        y: Tile Y coordinate
        style: Traffic style - 'relative' (relative to free-flow) or 'absolute' (actual speed)
        
    Returns:
        URL for traffic tile
    """
    if not config.TOMTOM_API_KEY:
        logger.warning("TomTom API key not configured")
        return ""
    
    # TomTom Traffic Flow Tiles API format
    # https://api.tomtom.com/traffic/map/4/tile/flow/{style}/{zoom}/{X}/{Y}.png?key={API_KEY}
    url = f"{config.TOMTOM_TILE_URL}/{style}/{z}/{x}/{y}.png"
    return url


def get_traffic_flow_data(lat: float, lon: float, zoom: int = 10) -> Optional[Dict]:
    """
    Get traffic flow data for a specific point.
    
    Args:
        lat: Latitude
        lon: Longitude
        zoom: Zoom level for detail (10-22, higher = more detail)
        
    Returns:
        Traffic flow data dict or None on error
    """
    if not config.TOMTOM_API_KEY:
        logger.error("TomTom API key not configured")
        return None
    
    # Check cache first
    cache_key = f"flow_{lat:.4f}_{lon:.4f}_{zoom}"
    cached = _get_cached_data(cache_key)
    if cached is not None:
        logger.debug(f"Returning cached traffic flow data for {lat},{lon}")
        return cached
    
    try:
        # TomTom Traffic Flow Segment Data API
        # https://api.tomtom.com/traffic/services/4/flowSegmentData/{style}/{zoom}/json
        params = {
            "key": config.TOMTOM_API_KEY,
            "point": f"{lat},{lon}",
            "unit": "KMPH"
        }
        
        url = f"{config.TOMTOM_TRAFFIC_FLOW_URL}/absolute/{zoom}/json"
        
        logger.debug(f"Fetching traffic flow data for point {lat},{lon}")
        
        response = requests.get(
            url,
            params=params,
            timeout=config.TOMTOM_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"TomTom Traffic Flow API error ({response.status_code}): {response.text}")
            return None
        
        data = response.json()
        
        # Cache the result
        _set_cached_data(cache_key, data)
        
        return data
        
    except requests.exceptions.Timeout:
        logger.error("TomTom Traffic Flow API request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"TomTom Traffic Flow API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_traffic_flow_data: {e}", exc_info=True)
        return None


def get_traffic_aware_eta(route_coords: List[List[float]]) -> Optional[Dict]:
    """
    Calculate traffic-aware ETA for a given route.
    
    Args:
        route_coords: List of [lat, lon] coordinates forming the route
        
    Returns:
        Dict with traffic-aware duration and other metadata, or None on error
        {
            "duration_seconds": int,      # Travel time with traffic
            "traffic_delay_seconds": int, # Additional time due to traffic
            "distance_meters": int,        # Route distance
            "traffic_status": str          # "clear", "moderate", or "heavy"
        }
    """
    if not config.TOMTOM_API_KEY:
        logger.error("TomTom API key not configured")
        return None
    
    if not route_coords or len(route_coords) < 2:
        logger.error("Invalid route_coords: need at least 2 points")
        return None
    
    # For very long routes, sample waypoints (TomTom allows up to 150 waypoints)
    max_waypoints = 50  # Use fewer for faster API response
    if len(route_coords) > max_waypoints:
        # Sample evenly
        step = len(route_coords) // max_waypoints
        sampled_coords = [route_coords[i] for i in range(0, len(route_coords), step)]
        # Ensure we include the last point
        if sampled_coords[-1] != route_coords[-1]:
            sampled_coords.append(route_coords[-1])
        route_coords = sampled_coords
    
    try:
        # Build waypoints string: lat1,lon1:lat2,lon2:...
        waypoints = ":".join([f"{lat},{lon}" for lat, lon in route_coords])
        
        # TomTom Routing API
        # GET https://api.tomtom.com/routing/1/calculateRoute/{locations}/json
        params = {
            "key": config.TOMTOM_API_KEY,
            "traffic": "true",  # Use live traffic
            "travelMode": "car",
            "computeBestOrder": "false",  # Keep order as provided
            "sectionType": "traffic",  # Get per-segment traffic data
            "routeRepresentation": "polyline"  # Get polyline for each leg
        }
        
        url = f"{config.TOMTOM_ROUTING_URL}/{waypoints}/json"
        
        logger.debug(f"Calculating traffic-aware ETA for route with {len(route_coords)} waypoints")
        
        response = requests.get(
            url,
            params=params,
            timeout=config.TOMTOM_TIMEOUT
        )
        
        if response.status_code != 200:
            logger.error(f"TomTom Routing API error ({response.status_code}): {response.text}")
            return None
        
        data = response.json()
        
        if "routes" not in data or len(data["routes"]) == 0:
            logger.error("No routes in TomTom API response")
            return None
        
        route = data["routes"][0]
        summary = route.get("summary", {})
        
        # Extract traffic data
        traffic_duration = summary.get("travelTimeInSeconds", 0)
        no_traffic_duration = summary.get("noTrafficTravelTimeInSeconds", 0)
        distance = summary.get("lengthInMeters", 0)
        
        # Debug log - show what TomTom returned
        logger.info(f"  TomTom API returned: travelTime={traffic_duration}s, noTrafficTime={no_traffic_duration}s, distance={distance}m")
        
        # If noTrafficTravelTimeInSeconds is 0 or missing, use travelTimeInSeconds as baseline (assume no delay)
        if no_traffic_duration == 0:
            logger.warning("  noTrafficTravelTimeInSeconds is 0, TomTom might not have historical data for this route")
            no_traffic_duration = traffic_duration  # Assume no delay if no baseline
        
        # Calculate traffic delay
        traffic_delay = traffic_duration - no_traffic_duration
        
        # Determine traffic status
        if traffic_delay <= 0 or no_traffic_duration == 0:
            traffic_status = "clear"
        else:
            delay_ratio = traffic_delay / no_traffic_duration
            if delay_ratio < 0.15:  # Less than 15% delay
                traffic_status = "clear"
            elif delay_ratio < 0.35:  # 15-35% delay
                traffic_status = "moderate"
            else:  # More than 35% delay
                traffic_status = "heavy"
        
        result = {
            "duration_seconds": traffic_duration,
            "no_traffic_duration_seconds": no_traffic_duration,
            "traffic_delay_seconds": max(0, traffic_delay),
            "distance_meters": distance,
            "traffic_status": traffic_status,
            "traffic_sections": []  # Per-segment traffic data
        }
        
        # Parse traffic sections for per-segment visualization
        sections = route.get("sections", [])
        legs = route.get("legs", [])
        
        # Get route points for mapping section indices
        all_points = []
        for leg in legs:
            for point in leg.get("points", []):
                all_points.append([point["latitude"], point["longitude"]])
        
        for section in sections:
            if section.get("sectionType") == "TRAFFIC":
                start_idx = section.get("startPointIndex", 0)
                end_idx = section.get("endPointIndex", 0)
                
                # Get traffic severity
                # simpleCategory: JAM, ROAD_WORK, ROAD_CLOSURE, or OTHER
                # magnitudeOfDelay: 0=unknown, 1=minor, 2=moderate, 3=major, 4=undefined
                simple_category = section.get("simpleCategory", "")
                magnitude = section.get("magnitudeOfDelay", 0)
                effective_speed = section.get("effectiveSpeedInKmh", 0)
                delay_in_seconds = section.get("delayInSeconds", 0)
                
                # Determine segment status
                if simple_category == "JAM" or magnitude >= 3:
                    segment_status = "heavy"
                elif magnitude >= 2 or simple_category in ["ROAD_WORK", "OTHER"]:
                    segment_status = "moderate"
                else:
                    segment_status = "clear"
                
                # Get segment coordinates
                segment_coords = all_points[start_idx:end_idx+1] if end_idx < len(all_points) else []
                
                if segment_coords:
                    result["traffic_sections"].append({
                        "coords": segment_coords,
                        "status": segment_status,
                        "delay": delay_in_seconds,
                        "speed": effective_speed,
                        "category": simple_category
                    })
        
        logger.info(f"  Traffic-aware ETA: {traffic_duration}s, delay: {traffic_delay}s, sections: {len(result['traffic_sections'])}")
        
        return result
        
    except requests.exceptions.Timeout:
        logger.error("TomTom Routing API request timed out")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"TomTom Routing API request failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error in get_traffic_aware_eta: {e}", exc_info=True)
        return None


def estimate_route_traffic(route_coords: List[List[float]], sample_points: int = 5) -> Dict:
    """
    Estimate overall traffic conditions along a route by sampling points.
    
    Args:
        route_coords: List of [lat, lon] coordinates
        sample_points: Number of points to sample along the route
        
    Returns:
        Dict with aggregated traffic info:
        {
            "average_speed_kmph": float,
            "free_flow_speed_kmph": float,
            "traffic_status": str,  # "clear", "moderate", "heavy"
            "congested_segments": int  # Number of congested segments
        }
    """
    if not route_coords or len(route_coords) < 2:
        return {
            "average_speed_kmph": 0,
            "free_flow_speed_kmph": 0,
            "traffic_status": "unknown",
            "congested_segments": 0
        }
    
    # Sample evenly along route
    sample_indices = [int(i * len(route_coords) / sample_points) for i in range(sample_points)]
    sample_indices = [min(i, len(route_coords) - 1) for i in sample_indices]
    
    speeds = []
    free_flow_speeds = []
    congested = 0
    
    for idx in sample_indices:
        lat, lon = route_coords[idx]
        flow_data = get_traffic_flow_data(lat, lon)
        
        if flow_data and "flowSegmentData" in flow_data:
            segment = flow_data["flowSegmentData"]
            current_speed = segment.get("currentSpeed", 0)
            free_flow_speed = segment.get("freeFlowSpeed", 0)
            
            if current_speed > 0:
                speeds.append(current_speed)
            if free_flow_speed > 0:
                free_flow_speeds.append(free_flow_speed)
            
            # Check if congested (current speed < 70% of free flow)
            if free_flow_speed > 0 and current_speed < 0.7 * free_flow_speed:
                congested += 1
    
    # Calculate averages
    avg_speed = sum(speeds) / len(speeds) if speeds else 0
    avg_free_flow = sum(free_flow_speeds) / len(free_flow_speeds) if free_flow_speeds else 0
    
    # Determine overall status
    if avg_free_flow > 0:
        speed_ratio = avg_speed / avg_free_flow
        if speed_ratio >= 0.85:
            traffic_status = "clear"
        elif speed_ratio >= 0.65:
            traffic_status = "moderate"
        else:
            traffic_status = "heavy"
    else:
        traffic_status = "unknown"
    
    return {
        "average_speed_kmph": round(avg_speed, 1),
        "free_flow_speed_kmph": round(avg_free_flow, 1),
        "traffic_status": traffic_status,
        "congested_segments": congested
    }


def get_route_traffic_segments(route_coords: List[List[float]], sample_interval: int = 10) -> List[Dict]:
    """
    Sample traffic along the ORS route and create colored segments.
    
    Instead of using TomTom's route (which differs from ORS), this function
    samples traffic at points along the ORS route and colors each segment
    based on traffic conditions at those points.
    
    Args:
        route_coords: List of [lat, lon] coordinates from ORS route
        sample_interval: Sample traffic every N points (to reduce API calls)
        
    Returns:
        List of segments with coords and status:
        [
            {"coords": [[lat, lon], ...], "status": "clear|moderate|heavy"},
            ...
        ]
    """
    if not route_coords or len(route_coords) < 2:
        return []
    
    if not config.TOMTOM_API_KEY:
        return []
    
    segments = []
    current_segment_coords = []
    current_status = None
    
    # Sample every N points to reduce API calls
    for i, coord in enumerate(route_coords):
        lat, lon = coord[0], coord[1]
        
        # Determine status for this point
        if i % sample_interval == 0 or i == len(route_coords) - 1:
            # Sample traffic at this point
            flow_data = get_traffic_flow_data(lat, lon, zoom=15)
            
            if flow_data and "flowSegmentData" in flow_data:
                segment_data = flow_data["flowSegmentData"]
                current_speed = segment_data.get("currentSpeed", 0)
                free_flow_speed = segment_data.get("freeFlowSpeed", 0)
                
                # Determine status based on speed ratio
                if free_flow_speed > 0 and current_speed > 0:
                    speed_ratio = current_speed / free_flow_speed
                    if speed_ratio >= 0.75:
                        point_status = "clear"
                    elif speed_ratio >= 0.50:
                        point_status = "moderate"
                    else:
                        point_status = "heavy"
                else:
                    point_status = "clear"  # Default to clear if no data
            else:
                point_status = "clear"  # Default to clear if API fails
            
            # Check if status changed
            if current_status is None:
                current_status = point_status
            
            if point_status != current_status and len(current_segment_coords) > 0:
                # Status changed - save current segment and start new one
                segments.append({
                    "coords": current_segment_coords.copy(),
                    "status": current_status
                })
                # Start new segment with overlap point for continuity
                current_segment_coords = [current_segment_coords[-1]] if current_segment_coords else []
                current_status = point_status
        
        # Add point to current segment
        current_segment_coords.append([lat, lon])
    
    # Don't forget the last segment
    if current_segment_coords and len(current_segment_coords) >= 2:
        segments.append({
            "coords": current_segment_coords,
            "status": current_status or "clear"
        })
    
    logger.info(f"  Created {len(segments)} traffic segments from {len(route_coords)} route points")
    
    return segments
