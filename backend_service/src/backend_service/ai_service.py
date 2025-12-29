"""
AI service integration module.
Handles flood detection by sending camera images to AI service.
"""
import httpx
import asyncio
from typing import List, Dict, Optional
from .logger import logger
from . import config
from .camera_service import get_camera_service
from .get_image import create_session, get_image_by_id

async def check_flood_status(camera_ids: List[str]) -> List[Dict]:
    """
    Check flood status for a list of cameras by ID.
    
    Args:
        camera_ids: List of camera IDs to check
        
    Returns:
        List of coordinates that are flooded: [{"lat": float, "lng": float}, ...]
    """
    if not camera_ids:
        logger.info("No cameras to check")
        return []
    
    logger.info(f"Checking flood status for {len(camera_ids)} cameras")
    flooded_coords = []
    
    # Get camera service
    camera_service = get_camera_service()
    
    # Validate camera IDs
    valid_ids, invalid_ids = camera_service.validate_camera_ids(camera_ids)
    if invalid_ids:
        logger.warning(f"Invalid camera IDs: {invalid_ids}")
    
    if not valid_ids:
        logger.warning("No valid camera IDs to process")
        return []
    
    # Create session for image fetching (synchronous)
    image_session = create_session()
    
    async with httpx.AsyncClient(timeout=config.AI_SERVICE_TIMEOUT) as client:
        tasks = []
        for cam_id in valid_ids:
            tasks.append(_process_camera(client, image_session, cam_id))
        
        # Run requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Error processing camera: {result}")
                continue
            
            if result:
                flooded_coords.append(result)
    
    logger.info(f"Found {len(flooded_coords)} flooded locations")
    return flooded_coords

async def _process_camera(client: httpx.AsyncClient, image_session, cam_id: str) -> Optional[Dict]:
    """
    Process a single camera: fetch image and classify.
    
    Args:
        client: httpx.AsyncClient for AI service requests
        image_session: requests.Session for image fetching
        cam_id: Camera ID
        
    Returns:
        Camera coordinates if flooded, None otherwise
    """
    camera_service = get_camera_service()
    camera = camera_service.get_camera(cam_id)
    
    if not camera:
        logger.warning(f"Camera {cam_id} not found in dataset")
        return None
    
    try:
        # Fetch image from camera (returns tuple: image_bytes, is_valid)
        logger.debug(f"Fetching image for camera {cam_id}")
        image_result = get_image_by_id(image_session, cam_id)
        
        if not image_result or not image_result[0]:
            logger.warning(f"Failed to fetch image for camera {cam_id}")
            return None
        
        image_bytes, is_valid = image_result
        
        # Skip processing if image is invalid
        if not is_valid:
            logger.warning(f"Camera {cam_id} returned invalid image, skipping AI processing")
            return None
        
        # Send image to AI Service
        logger.debug(f"Sending image for camera {cam_id} to AI service")
        files = {'file': ('snapshot.jpg', image_bytes, 'image/jpeg')}
        
        for attempt in range(config.AI_SERVICE_MAX_RETRIES):
            try:
                response = await client.post(config.AI_SERVICE_URL, files=files)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success") and result.get("prediction", {}).get("class") == "flood":
                        confidence = result.get("prediction", {}).get("confidence", 0)
                        logger.info(f"Camera {cam_id} detected flood (confidence: {confidence:.2f})")
                        return camera["coords"]
                    else:
                        logger.debug(f"Camera {cam_id} prediction: {result.get('prediction', {}).get('class', 'unknown')}")
                        return None
                else:
                    logger.warning(f"AI Service returned {response.status_code} for camera {cam_id}: {response.text}")
                    if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                        await asyncio.sleep(0.5)  # Brief delay before retry
                        continue
                    return None
                    
            except httpx.TimeoutException:
                logger.warning(f"Timeout calling AI service for camera {cam_id} (attempt {attempt + 1}/{config.AI_SERVICE_MAX_RETRIES})")
                if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
                return None
            except httpx.RequestError as e:
                logger.warning(f"Request error calling AI service for camera {cam_id}: {e}")
                if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
                return None
        
        return None
            
    except Exception as e:
        logger.error(f"Exception processing camera {cam_id}: {e}", exc_info=True)
        return None


async def check_flood_status_for_all(camera_ids: List[str]) -> Dict[str, Dict]:
    """
    Check flood status for all cameras and return detailed results.
    Used by the scheduler to update FloodStateManager.
    
    Args:
        camera_ids: List of all camera IDs to check
        
    Returns:
        Dict mapping camera_id -> {"is_flooded": bool, "confidence": float}
    """
    if not camera_ids:
        logger.info("No cameras to check")
        return {}
    
    logger.info(f"Checking flood status for {len(camera_ids)} cameras")
    results: Dict[str, Dict] = {}
    
    # Initialize all as not flooded
    for cam_id in camera_ids:
        results[cam_id] = {"is_flooded": False, "confidence": 0.0}
    
    # Get camera service
    camera_service = get_camera_service()
    
    # Validate camera IDs
    valid_ids, invalid_ids = camera_service.validate_camera_ids(camera_ids)
    if invalid_ids:
        logger.warning(f"Invalid camera IDs: {invalid_ids}")
    
    if not valid_ids:
        logger.warning("No valid camera IDs to process")
        return results
    
    # Create session for image fetching (synchronous)
    image_session = create_session()
    
    # Progress tracking
    processed_count = 0
    total_count = len(valid_ids)
    
    async with httpx.AsyncClient(timeout=config.AI_SERVICE_TIMEOUT) as client:
        tasks = []
        for cam_id in valid_ids:
            tasks.append(_process_camera_detailed(client, image_session, cam_id))
        
        # Run requests concurrently and track progress
        logger.info(f"Processing 0/{total_count} cameras...")
        task_results = []
        
        # Process in chunks to show progress
        chunk_size = 10
        for i in range(0, len(tasks), chunk_size):
            chunk = tasks[i:i + chunk_size]
            chunk_results = await asyncio.gather(*chunk, return_exceptions=True)
            task_results.extend(chunk_results)
            
            processed_count = min(i + chunk_size, total_count)
            logger.info(f"Processed {processed_count}/{total_count} cameras...")
        
        for cam_id, result in zip(valid_ids, task_results):
            if isinstance(result, Exception):
                logger.error(f"Error processing camera {cam_id}: {result}")
                continue
            
            if result:
                results[cam_id] = result
    
    flooded_count = sum(1 for r in results.values() if r.get('is_flooded'))
    logger.info(f"Flood check complete: {flooded_count}/{len(camera_ids)} flooded")
    return results


async def _process_camera_detailed(client: httpx.AsyncClient, image_session, cam_id: str) -> Dict:
    """
    Process a single camera and return detailed result.
    
    Args:
        client: httpx.AsyncClient for AI service requests
        image_session: requests.Session for image fetching
        cam_id: Camera ID
        
    Returns:
        {"is_flooded": bool, "confidence": float}
    """
    camera_service = get_camera_service()
    camera = camera_service.get_camera(cam_id)
    
    if not camera:
        logger.warning(f"Camera {cam_id} not found in dataset")
        return {"is_flooded": False, "confidence": 0.0}
    
    try:
        # Fetch image from camera (returns tuple: image_bytes, is_valid)
        logger.debug(f"Fetching image for camera {cam_id}")
        image_result = get_image_by_id(image_session, cam_id)
        
        if not image_result or not image_result[0]:
            logger.warning(f"Failed to fetch image for camera {cam_id}")
            # Mark camera as invalid in flood state
            from .flood_state import get_flood_state_manager
            flood_manager = get_flood_state_manager()
            flood_manager.update_camera_validity(cam_id, False)
            return {"is_flooded": False, "confidence": 0.0, "is_valid": False}
        
        image_bytes, is_valid = image_result
        
        # Update camera validity in flood state
        from .flood_state import get_flood_state_manager
        flood_manager = get_flood_state_manager()
        flood_manager.update_camera_validity(cam_id, is_valid)
        
        # Skip AI processing if image is invalid
        if not is_valid:
            logger.warning(f"Camera {cam_id} returned invalid image, skipping AI processing")
            return {"is_flooded": False, "confidence": 0.0, "is_valid": False}
        
        # Send image to AI Service
        logger.debug(f"Sending image for camera {cam_id} to AI service")
        files = {'file': ('snapshot.jpg', image_bytes, 'image/jpeg')}
        
        for attempt in range(config.AI_SERVICE_MAX_RETRIES):
            try:
                response = await client.post(config.AI_SERVICE_URL, files=files)
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        prediction = result.get("prediction", {})
                        is_flooded = prediction.get("class") == "flood"
                        confidence = prediction.get("confidence", 0.0)
                        return {"is_flooded": is_flooded, "confidence": confidence}
                    else:
                        return {"is_flooded": False, "confidence": 0.0}
                else:
                    logger.warning(f"AI Service returned {response.status_code} for camera {cam_id}")
                    if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return {"is_flooded": False, "confidence": 0.0}
                    
            except httpx.TimeoutException:
                logger.warning(f"Timeout for camera {cam_id} (attempt {attempt + 1})")
                if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
                return {"is_flooded": False, "confidence": 0.0}
            except httpx.RequestError as e:
                logger.warning(f"Request error for camera {cam_id}: {e}")
                if attempt < config.AI_SERVICE_MAX_RETRIES - 1:
                    await asyncio.sleep(0.5)
                    continue
                return {"is_flooded": False, "confidence": 0.0}
        
        return {"is_flooded": False, "confidence": 0.0}
            
    except Exception as e:
        logger.error(f"Exception processing camera {cam_id}: {e}", exc_info=True)
        return {"is_flooded": False, "confidence": 0.0}
