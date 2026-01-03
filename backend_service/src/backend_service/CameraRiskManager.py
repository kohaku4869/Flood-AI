"""
Camera Risk Manager module.
Calculates flood risk based on weather, tide, and camera-specific coefficients.
Persists coefficient updates to CSV.
"""
import pandas as pd
from datetime import datetime
from pathlib import Path
from . import config
from .logger import logger


class CameraRiskManager:
    """
    Calculates flood risk for cameras and updates learning coefficients.
    Persists updated coefficients back to the camera dataset CSV.
    """
    
    def __init__(self, csv_path: Path = None):
        """
        Initialize risk manager.
        
        Args:
            csv_path: Path to camera dataset CSV. Uses config default if None.
        """
        self.csv_path = csv_path or config.CAMERA_DATASET_PATH
        self.eta = 0.03  # Learning rate for coefficient updates
        self.critical = config.CRITICAL
        self.weights = config.WEIGHTS
    
    def normalize_rain(self, rain_3h: float) -> float:
        """Normalize 3-hour rain to [0, 1] range."""
        return min(rain_3h / self.critical["rain_3h_mm"], 1.0)

    def normalize_tide(self, tide: float) -> float:
        """Normalize tide level to [0, 1] range."""
        return min(tide / self.critical["tide_m"], 1.0)

    def normalize_tide_delta(self, tide_delta: float) -> float:
        """Normalize tide change to [0, 1] range."""
        return min(tide_delta / self.critical["tide_delta_m"], 1.0)

    def compute_base_risk(self, weather: dict, tide: dict) -> float:
        """
        Compute base risk from weather and tide data (without camera-specific coefficient).
        
        Args:
            weather: Dict with 'total_rain_3h' from RainFetcher
            tide: Dict with 'tide_now' and 'tide_delta' from TideFetcher
            
        Returns:
            Base risk score [0, 1]
        """
        R = self.normalize_rain(weather.get("total_rain_3h", 0))
        T = self.normalize_tide(tide.get("tide_now", 0))
        D = self.normalize_tide_delta(tide.get("tide_delta", 0))

        base_risk = (
            self.weights["rain"] * R +
            self.weights["tide"] * T +
            self.weights["tide_trend"] * D
        )

        return base_risk

    def compute_risk(self, weather: dict, tide: dict, camera: dict) -> tuple[float, float]:
        """
        Compute total flood risk for a camera.
        
        Args:
            weather: Weather data from RainFetcher
            tide: Tide data from TideFetcher  
            camera: Camera dict with 'Coef' key
            
        Returns:
            Tuple of (total_risk, base_risk), both in [0, 1]
        """
        base_risk = self.compute_base_risk(weather, tide)
        
        coef = camera.get("Coef", 0.3)  # Default coefficient

        risk = (
            base_risk +
            self.weights["coef"] * coef
        )

        return max(0.0, min(risk, 1.0)), base_risk

    def update_coef(self, camera: dict, error: float, base_risk: float) -> None:
        """
        Update camera coefficient based on prediction error.
        Only updates when base_risk is significant (>= 0.4).
        
        Args:
            camera: Camera dict (will be modified in place)
            error: Difference between predicted and actual risk
            base_risk: Base risk used for weighting update
        """
        if base_risk < 0.4:
            return

        current_coef = camera.get("Coef", 0.3)
        new_coef = current_coef + self.eta * error * base_risk
        new_coef = max(0.0, min(1.0, new_coef))
        
        camera["Coef"] = new_coef
        camera["Last_Update"] = datetime.now().strftime("%Y-%m-%d %H:%M")

    def save_cameras_to_csv(self, cameras: list[dict]) -> None:
        """
        Save updated camera data back to CSV file.
        
        Args:
            cameras: List of camera dicts to persist
        """
        try:
            df = pd.DataFrame(cameras)
            # Ensure column order matches original
            columns = ["CamId", "Street_Name", "Latitude", "Longitude", "Coef", "Last_Update"]
            df = df[columns]
            df.to_csv(self.csv_path, index=False)
            logger.info(f"Saved {len(cameras)} cameras to {self.csv_path}")
        except Exception as e:
            logger.error(f"Failed to save cameras to CSV: {e}")
            raise

    def risk_level(self, risk: float) -> str:
        """
        Convert numeric risk to categorical level.
        
        Args:
            risk: Risk score [0, 1]
            
        Returns:
            Risk level string: 'low', 'medium', 'high', or 'very high'
        """
        for level, threshold in config.RISK_THRESHOLDS.items():
            if risk < threshold:
                return level
        return "very high"
