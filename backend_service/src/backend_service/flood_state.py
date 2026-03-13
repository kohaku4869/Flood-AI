"""
Flood state management module.
Manages the flood status of all cameras with support for test mode.
"""
import random
import threading
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from .logger import logger


@dataclass
class CameraFloodState:
    """Represents the flood state of a single camera."""
    camera_id: str
    is_flooded: bool
    coords: Dict[str, float]  # {"lat": float, "lng": float}
    street_name: str = ""  # Camera location name
    last_checked: Optional[datetime] = None
    confidence: float = 0.0
    is_valid: bool = True  # Whether camera is returning valid images


class FloodStateManager:
    """
    Singleton manager for camera flood states.
    Thread-safe for concurrent access.
    """
    _instance: Optional['FloodStateManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._states: Dict[str, CameraFloodState] = {}
        self._test_mode: bool = False
        self._test_flooded_ids: set = set()
        self._test_metadata: Dict[str, Dict] = {}  # Store test-specific metadata
        self._state_lock = threading.RLock()
        self._initialized = True
        logger.info("FloodStateManager initialized")
    
    @property
    def test_mode(self) -> bool:
        """Check if test mode is enabled."""
        return self._test_mode
    
    def initialize_cameras(self, cameras: Dict[str, Dict]) -> None:
        """
        Initialize all camera states from camera service data.
        
        Args:
            cameras: Dict of camera_id -> camera_info from CameraService
        """
        with self._state_lock:
            for cam_id, cam_info in cameras.items():
                self._states[cam_id] = CameraFloodState(
                    camera_id=cam_id,
                    is_flooded=False,
                    coords=cam_info['coords'],
                    street_name=cam_info.get('street_name', ''),
                    last_checked=None,
                    confidence=0.0
                )
            logger.info(f"Initialized flood states for {len(self._states)} cameras")
    
    def update_camera_state(self, camera_id: str, is_flooded: bool, 
                           confidence: float = 0.0) -> None:
        """
        Update the flood state for a single camera.
        
        Args:
            camera_id: Camera ID
            is_flooded: Whether the camera location is flooded
            confidence: AI prediction confidence
        """
        with self._state_lock:
            if camera_id in self._states:
                self._states[camera_id].is_flooded = is_flooded
                self._states[camera_id].confidence = confidence
                self._states[camera_id].last_checked = datetime.now()
    
    def update_camera_validity(self, camera_id: str, is_valid: bool) -> None:
        """
        Update the validity state for a single camera.
        
        Args:
            camera_id: Camera ID
            is_valid: Whether the camera is returning valid images
        """
        with self._state_lock:
            if camera_id in self._states:
                self._states[camera_id].is_valid = is_valid
                logger.debug(f"Camera {camera_id} validity updated to {is_valid}")
    
    def get_flooded_coords(self) -> List[Dict[str, float]]:
        """
        Get coordinates of all flooded locations.
        
        Returns:
            List of {"lat": float, "lng": float} for flooded cameras
        """
        with self._state_lock:
            if self._test_mode:
                return [
                    self._states[cam_id].coords 
                    for cam_id in self._test_flooded_ids 
                    if cam_id in self._states
                ]
            else:
                return [
                    state.coords 
                    for state in self._states.values() 
                    if state.is_flooded
                ]
    
    def get_all_states(self) -> List[Dict]:
        """
        Get all camera states for API response.
        
        Returns:
            List of camera state dictionaries
        """
        with self._state_lock:
            states = []
            for cam_id, state in self._states.items():
                is_flooded = cam_id in self._test_flooded_ids if self._test_mode else state.is_flooded
                
                # Use test metadata if in test mode
                confidence = state.confidence
                last_checked = state.last_checked
                
                if self._test_mode:
                    if is_flooded:
                        test_info = self._test_metadata.get(cam_id, {})
                        confidence = test_info.get('confidence', 0.95)
                        last_checked = test_info.get('last_checked', state.last_checked)
                    else:
                        confidence = 0.05
                
                states.append({
                    "camera_id": cam_id,
                    "name": state.street_name or cam_id,
                    "is_flooded": is_flooded,
                    "is_valid": state.is_valid,
                    "coords": state.coords,
                    "last_checked": last_checked.isoformat() if last_checked else None,
                    "confidence": confidence
                })
            return states
    
    def enable_test_mode(self, flood_percentage: float = 0.1) -> int:
        """
        Enable test mode with random flooded cameras.
        
        Args:
            flood_percentage: Fraction of cameras to mark as flooded (0.0-1.0)
            
        Returns:
            Number of cameras marked as flooded
        """
        with self._state_lock:
            self._test_mode = True
            all_ids = list(self._states.keys())
            num_flooded = int(len(all_ids) * flood_percentage)
            self._test_flooded_ids = set(random.sample(all_ids, num_flooded))
            
            # Generate random metadata for flooded cameras
            # Accuracy 90-100%, Time -5 to -1 minutes
            from datetime import timedelta
            self._test_metadata = {}
            for cam_id in self._test_flooded_ids:
                confidence = random.uniform(0.90, 1.00)
                minutes_ago = random.uniform(1, 5)
                last_checked = datetime.now() - timedelta(minutes=minutes_ago)
                self._test_metadata[cam_id] = {
                    "confidence": confidence,
                    "last_checked": last_checked
                }
                
            logger.info(f"Test mode enabled: {num_flooded} cameras marked as flooded")
            return num_flooded
    
    def disable_test_mode(self) -> None:
        """Disable test mode and return to real states."""
        with self._state_lock:
            self._test_mode = False
            self._test_flooded_ids.clear()
            logger.info("Test mode disabled, using real flood states")
    
    def get_flooded_count(self) -> int:
        """Get count of flooded cameras."""
        with self._state_lock:
            if self._test_mode:
                return len(self._test_flooded_ids)
            return sum(1 for s in self._states.values() if s.is_flooded)
    
    def get_total_count(self) -> int:
        """Get total number of cameras."""
        with self._state_lock:
            return len(self._states)


def get_flood_state_manager() -> FloodStateManager:
    """Get the singleton FloodStateManager instance."""
    return FloodStateManager()
