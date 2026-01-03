"""
Camera service module for loading and managing camera dataset.
Provides access to camera information from CSV file.
"""
import pandas as pd
from typing import Dict, List, Optional
from pathlib import Path
from .logger import logger
from . import config
from datetime import datetime
class CameraService:
    """Service for managing camera dataset."""
    
    def __init__(self, csv_path: Path):
        """
        Initialize camera service with CSV data.
        
        Args:
            csv_path: Path to camera dataset CSV file
        """
        self.csv_path = csv_path
        self.cameras: Dict[str, Dict] = {}
        self._load_cameras()
    
    def _load_cameras(self):
        """Load camera data from CSV file."""
        try:
            if not self.csv_path.exists():
                logger.error(f"Camera dataset not found at {self.csv_path}")
                raise FileNotFoundError(f"Camera dataset not found: {self.csv_path}")
            
            logger.info(f"Loading camera dataset from {self.csv_path}")
            df = pd.read_csv(self.csv_path)
            
            # Convert to dictionary indexed by CamId
            for _, row in df.iterrows():
                cam_id = str(row['CamId'])
                self.cameras[cam_id] = {
                    'CamId': cam_id,
                    'Street_Name': row['Street_Name'],
                    'Latitude': float(row['Latitude']),
                    'Longitude': float(row['Longitude']),
                    'Coef': float(row['Coef']),
                    'Last_Update': row['Last_Update'],
                    # Also keep convenience keys for backwards compatibility
                    'id': cam_id,
                    'street_name': row['Street_Name'],
                    'coords': {
                        'lat': float(row['Latitude']),
                        'lng': float(row['Longitude'])
                    }
                }
            
            logger.info(f"Loaded {len(self.cameras)} cameras from dataset")
            
        except Exception as e:
            logger.error(f"Error loading camera dataset: {e}")
            raise
    
    def get_camera(self, cam_id: str) -> Optional[Dict]:
        """
        Get camera information by ID.
        
        Args:
            cam_id: Camera ID
            
        Returns:
            Camera information dictionary or None if not found
        """
        return self.cameras.get(cam_id)
    
    def get_cameras(self, cam_ids: List[str]) -> List[Dict]:
        """
        Get multiple cameras by IDs.
        
        Args:
            cam_ids: List of camera IDs
            
        Returns:
            List of camera information dictionaries (skips invalid IDs)
        """
        cameras = []
        for cam_id in cam_ids:
            camera = self.get_camera(cam_id)
            if camera:
                cameras.append(camera)
            else:
                logger.warning(f"Camera ID {cam_id} not found in dataset")
        return cameras
    
    def get_cameras_info(self) -> List[Dict]:
        """
        Get all camera information.
        
        Returns:
            List of camera information dictionaries
        """
        return list(self.cameras.values())
    
    def validate_camera_ids(self, cam_ids: List[str]) -> tuple[List[str], List[str]]:
        """
        Validate a list of camera IDs.
        
        Args:
            cam_ids: List of camera IDs to validate
            
        Returns:
            Tuple of (valid_ids, invalid_ids)
        """
        valid_ids = []
        invalid_ids = []
        
        for cam_id in cam_ids:
            if cam_id in self.cameras:
                valid_ids.append(cam_id)
            else:
                invalid_ids.append(cam_id)
        
        return valid_ids, invalid_ids
    
    def get_cameras_in_bbox(self, min_lat: float, max_lat: float, 
                            min_lng: float, max_lng: float) -> List[Dict]:
        """
        Get cameras within a bounding box.
        
        Args:
            min_lat: Minimum latitude
            max_lat: Maximum latitude
            min_lng: Minimum longitude
            max_lng: Maximum longitude
            
        Returns:
            List of cameras within the bounding box
        """
        cameras = []
        for camera in self.cameras.values():
            lat = camera['coords']['lat']
            lng = camera['coords']['lng']
            if min_lat <= lat <= max_lat and min_lng <= lng <= max_lng:
                cameras.append(camera)
        return cameras


# Global camera service instance
_camera_service: Optional[CameraService] = None

def get_camera_service() -> CameraService:
    """Get the global camera service instance."""
    global _camera_service
    if _camera_service is None:
        _camera_service = CameraService(config.CAMERA_DATASET_PATH)
    return _camera_service
