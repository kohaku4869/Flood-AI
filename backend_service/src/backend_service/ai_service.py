import httpx
import asyncio

AI_SERVICE_URL = "http://localhost:5000/api/v1/predict"

async def check_flood_status(camera_data):
    """
    Check flood status for a list of cameras.
    
    Args:
        camera_data (list): List of dicts containing camera info.
                            Example: [{"id": "cam1", "coords": {"lat": 21.0, "lng": 105.8}, "snapshot_url": "..."}]
    
    Returns:
        list: List of coordinates that are flooded.
    """
    flooded_coords = []
    
    async with httpx.AsyncClient() as client:
        tasks = []
        for cam in camera_data:
            tasks.append(_process_camera(client, cam))
        
        # Run requests concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, Exception):
                print(f"Error processing camera: {result}")
                continue
            
            if result:
                flooded_coords.append(result)

    return flooded_coords

async def _process_camera(client, cam):
    """Process a single camera: fetch image and classify."""
    try:
        # 1. Fetch image from snapshot_url
        snapshot_url = cam.get("snapshot_url")
        if not snapshot_url:
            print(f"No snapshot URL for camera {cam.get('id')}")
            return None

        # In a real scenario, we would fetch the image. 
        # For now, we assume the URL is accessible or mocked.
        img_response = await client.get(snapshot_url)
        if img_response.status_code != 200:
            print(f"Failed to fetch image for camera {cam.get('id')}: {img_response.status_code}")
            return None
        
        image_bytes = img_response.content

        # 2. Send image to AI Service
        files = {'file': ('snapshot.jpg', image_bytes, 'image/jpeg')}
        response = await client.post(AI_SERVICE_URL, files=files)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("success") and result.get("prediction", {}).get("class") == "flood":
                return cam["coords"]
        else:
            print(f"AI Service returned {response.status_code} for camera {cam.get('id')}: {response.text}")
            
    except Exception as e:
        print(f"Exception processing camera {cam.get('id')}: {e}")
        raise e
    
    return None
