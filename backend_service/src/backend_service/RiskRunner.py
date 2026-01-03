"""
Risk Runner module.
Orchestrates flood risk prediction across all cameras.
"""
from datetime import datetime
from pathlib import Path
from typing import List, Dict

from .CameraRiskManager import CameraRiskManager
from .camera_service import get_camera_service
from .WeatherService import RainFetcher, TideFetcher
from . import config
from .logger import logger


class RiskRunner:
    """
    Orchestrates flood risk prediction for all cameras.
    Coordinates weather/tide fetching, risk calculation, and coefficient updates.
    """
    
    # Risk color mapping for frontend
    RISK_COLORS = {
        "low": "#22c55e",       # green
        "medium": "#eab308",    # yellow
        "high": "#f97316",      # orange
        "very high": "#ef4444"  # red
    }
    
    def __init__(self):
        """Initialize all required services."""
        self.rain_fetcher = RainFetcher()
        self.tide_fetcher = TideFetcher(config.TIDE_DATA_PATH)
        self.camera_service = get_camera_service()
        self.risk_manager = CameraRiskManager()
        # Cache for multi-hour predictions: {hour_offset: [camera_results]}
        self._prediction_cache: Dict[int, List[Dict]] = {}
        self._cache_timestamp: datetime = None
    
    def predict(self, time_context: int = 0) -> List[Dict]:
        """
        Predict flood risk for all cameras at a given time offset.
        
        Args:
            time_context: Hours offset from current time (0 = now)
            
        Returns:
            List of camera dicts with updated risk scores
        """
        logger.info(f"Starting risk prediction for time_context={time_context}")
        start_time = datetime.now()
        
        # Fetch environmental data
        try:
            weather = self.rain_fetcher.fetch(time_context)
            tide = self.tide_fetcher.fetch(time_context)
        except Exception as e:
            logger.error(f"Failed to fetch weather/tide data: {e}")
            raise
        
        logger.info(f"Weather: {weather.get('total_rain_3h', 0):.1f}mm rain, "
                   f"Tide: {tide.get('tide_now', 0):.2f}m (delta: {tide.get('tide_delta', 0):.2f}m)")
        
        # Get all cameras from service
        cameras = list(self.camera_service.cameras.values())
        
        # Calculate risk for each camera
        results = []
        for camera in cameras:
            # Compute risk
            risk, base_risk = self.risk_manager.compute_risk(weather, tide, camera)
            risk_level = self.risk_manager.risk_level(risk)
            
            # Add risk to camera data
            camera_result = camera.copy()
            camera_result["risk"] = round(risk, 3)
            camera_result["base_risk"] = round(base_risk, 3)
            camera_result["risk_level"] = risk_level
            camera_result["risk_color"] = self.RISK_COLORS.get(risk_level, "#6b7280")
            camera_result["time_context"] = time_context
            
            results.append(camera_result)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        high_risk_count = sum(1 for r in results if r["risk"] >= 0.5)
        logger.info(f"Risk prediction completed in {elapsed:.2f}s: "
                   f"{high_risk_count}/{len(results)} cameras at medium+ risk")
        
        return results
    
    def predict_multi_hour(self, hours: List[int] = None) -> Dict[int, List[Dict]]:
        """
        Calculate risk predictions for multiple future hours.
        
        Args:
            hours: List of hour offsets to predict (default: 1-12)
            
        Returns:
            Dict mapping hour offset to list of camera predictions
        """
        if hours is None:
            hours = list(range(1, 13))  # 1-12 hours ahead
        
        logger.info(f"Calculating multi-hour predictions for hours: {hours}")
        start_time = datetime.now()
        
        predictions = {}
        for hour in hours:
            try:
                predictions[hour] = self.predict(time_context=hour)
            except Exception as e:
                logger.error(f"Failed to predict for hour {hour}: {e}")
                predictions[hour] = []
        
        # Cache results
        self._prediction_cache = predictions
        self._cache_timestamp = datetime.now()
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Multi-hour prediction completed in {elapsed:.2f}s")
        
        return predictions
    
    def get_cached_predictions(self, hour: int) -> List[Dict]:
        """
        Get cached predictions for a specific hour.
        
        Args:
            hour: Hour offset (1-12)
            
        Returns:
            List of camera predictions, or empty list if not cached
        """
        return self._prediction_cache.get(hour, [])
    
    def get_cache_timestamp(self) -> datetime:
        """Get the timestamp of the last cache update."""
        return self._cache_timestamp
    
    def update_from_observation(self, camera_id: str, observed_flooded: bool) -> None:
        """
        Update a camera's coefficient based on ground truth observation.
        
        Args:
            camera_id: ID of the camera
            observed_flooded: Whether flooding was actually observed
        """
        camera = self.camera_service.get_camera(camera_id)
        if not camera:
            logger.warning(f"Camera {camera_id} not found for observation update")
            return
        
        # Get current predictions
        try:
            weather = self.rain_fetcher.fetch(0)
            tide = self.tide_fetcher.fetch(0)
        except Exception as e:
            logger.error(f"Failed to fetch data for observation update: {e}")
            return
        
        # Calculate prediction error
        predicted_risk, base_risk = self.risk_manager.compute_risk(weather, tide, camera)
        actual_risk = 1.0 if observed_flooded else 0.0
        error = actual_risk - predicted_risk
        
        # Update coefficient
        self.risk_manager.update_coef(camera, error, base_risk)
        
        # Persist to CSV
        all_cameras = list(self.camera_service.cameras.values())
        self.risk_manager.save_cameras_to_csv(all_cameras)
        
        logger.info(f"Updated camera {camera_id} coef to {camera.get('Coef', 0.3):.3f} "
                   f"(error: {error:.2f})")
    
    def batch_update_from_ai(self, ai_results: Dict[str, Dict]) -> None:
        """
        Batch update coefficients from AI service predictions.
        
        Args:
            ai_results: Dict of camera_id -> {'is_flooded': bool, 'confidence': float}
        """
        logger.info(f"Batch updating {len(ai_results)} cameras from AI results")
        
        try:
            weather = self.rain_fetcher.fetch(0)
            tide = self.tide_fetcher.fetch(0)
        except Exception as e:
            logger.error(f"Failed to fetch data for batch update: {e}")
            return
        
        updated_count = 0
        for camera_id, result in ai_results.items():
            camera = self.camera_service.get_camera(camera_id)
            if not camera:
                continue
            
            # Calculate error (AI confidence-weighted)
            predicted_risk, base_risk = self.risk_manager.compute_risk(weather, tide, camera)
            is_flooded = result.get("is_flooded", False)
            confidence = result.get("confidence", 0.5)
            
            # Only update if AI is confident
            if confidence >= 0.7:
                actual_risk = 1.0 if is_flooded else 0.0
                error = actual_risk - predicted_risk
                self.risk_manager.update_coef(camera, error, base_risk)
                updated_count += 1
        
        # Persist all changes
        if updated_count > 0:
            all_cameras = list(self.camera_service.cameras.values())
            self.risk_manager.save_cameras_to_csv(all_cameras)
            logger.info(f"Persisted {updated_count} coefficient updates to CSV")