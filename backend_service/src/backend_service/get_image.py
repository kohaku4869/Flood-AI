"""
Image retrieval module for fetching camera snapshots.
"""
import requests
import time
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from .logger import logger
from . import config
from PIL import Image
import imagehash
from io import BytesIO
from pathlib import Path

# Disable InsecureRequestWarning for camera API requests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Load error template hash once at module level
_error_template_hash = None
_invalid_image_bytes = None

def _load_invalid_image_template():
    """Load the invalid image template and its hash."""
    global _error_template_hash, _invalid_image_bytes
    if _error_template_hash is None:
        try:
            invalid_image_path = config.INVALID_IMAGE_PATH
            if not Path(invalid_image_path).exists():
                logger.warning(f"Invalid image template not found at {invalid_image_path}")
                return
            
            with open(invalid_image_path, 'rb') as f:
                _invalid_image_bytes = f.read()
            
            error_template = Image.open(invalid_image_path)
            _error_template_hash = imagehash.phash(error_template)
            logger.info(f"Loaded invalid image template from {invalid_image_path}")
        except Exception as e:
            logger.error(f"Failed to load invalid image template: {e}")

# Load template on module import
_load_invalid_image_template()

def create_session():
    """
    Create a session with appropriate headers and retry logic for camera API.
    
    Returns:
        requests.Session: Configured session object
    """
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,  # Total number of retries
        backoff_factor=1,  # Wait 1s, 2s, 4s between retries
        status_forcelist=[429, 500, 502, 503, 504],  # Retry on these status codes
        allowed_methods=["GET"],  # Retry only on GET requests
        raise_on_status=False
    )
    
    # Use connection pooling with 10 connections for parallel requests
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://giaothong.hochiminhcity.gov.vn/"
    }
    session.headers.update(headers)
    
    # Initialize session by visiting homepage
    try:
        logger.debug("Initializing camera API session")
        session.get("https://giaothong.hochiminhcity.gov.vn/", timeout=10, verify=False)
    except Exception as e:
        logger.warning(f"Session initialization warning: {e}")
    
    return session

def is_image_valid(image_content):
    """
    Check if image content is valid (not an error/placeholder image).
    
    Args:
        image_content: Image bytes
        
    Returns:
        bool: True if valid, False if matches error template
    """
    if _error_template_hash is None:
        logger.warning("Error template not loaded, assuming image is valid")
        return True
    
    try:
        # Calculate hash of downloaded image
        current_image = Image.open(BytesIO(image_content))
        current_hash = imagehash.phash(current_image)
        
        # Compare. If hamming distance < 5, consider it an error image
        # (Threshold of 5 allows for slight noise while still detecting errors)
        if current_hash - _error_template_hash < 5:
            return False
        return True
    except Exception as e:
        logger.error(f"Error validating image: {e}")
        return True  # Assume valid if we can't validate

def get_image_by_id(session, camera_id):
    """
    Get camera image by ID.
    
    Args:
        session: requests.Session object
        camera_id: Camera ID string
        
    Returns:
        tuple: (image_bytes, is_valid) where:
            - image_bytes: Image data (either real or placeholder)
            - is_valid: True if real camera image, False if placeholder/error
    """
    try:
        ts = int(time.time() * 1000)  # Timestamp
        url = f"{config.CAMERA_BASE_URL}?id={camera_id}&bg=black&w=300&h=230&t={ts}"
        
        response = session.get(url, timeout=config.CAMERA_IMAGE_TIMEOUT, verify=False)
        
        if response.status_code == 200:
            # Validate image content
            is_valid = is_image_valid(response.content)
            
            if is_valid:
                logger.debug(f"Successfully fetched valid image for camera {camera_id}")
                return response.content, True
            else:
                logger.warning(f"Camera {camera_id} returned invalid/error image")
                # Return placeholder image
                if _invalid_image_bytes:
                    return _invalid_image_bytes, False
                else:
                    return response.content, False
        else:
            logger.warning(f"Failed to fetch image for camera {camera_id}: Status {response.status_code}")
            # Return placeholder image
            if _invalid_image_bytes:
                return _invalid_image_bytes, False
            else:
                return None, False
            
    except Exception as e:
        logger.error(f"Error fetching image for camera {camera_id}: {e}")
        # Return placeholder image on error
        if _invalid_image_bytes:
            return _invalid_image_bytes, False
        else:
            return None, False