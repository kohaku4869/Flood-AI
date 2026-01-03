"""
Training Data Logger module.
Logs weather, tide, and camera data to daily CSV files for model training.
"""
import os
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List
from . import config
from .logger import logger


class TrainingDataLogger:
    """
    Logs training data for flood prediction model.
    Creates daily CSV files with weather, tide, and camera features.
    """
    
    # CSV columns for training data
    COLUMNS = [
        "timestamp",
        "camera_id",
        "rain_prev_1h",
        "rain_prev_3h",
        "rain_next_1h", 
        "rain_next_3h",
        "tide_now",
        "tide_prev_1h",
        "tide_next_1h",
        "tide_next_3h",
        "camera_coef"
    ]
    
    def __init__(self, log_dir: Path = None):
        """
        Initialize the training data logger.
        
        Args:
            log_dir: Directory for log files. Defaults to config.TRAINING_DATA_DIR
        """
        self.log_dir = log_dir or getattr(config, 'TRAINING_DATA_DIR', 
                                           Path(config.project_root) / "logs" / "training_data")
        self._ensure_dir_exists()
    
    def _ensure_dir_exists(self):
        """Create log directory if it doesn't exist."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Training data directory: {self.log_dir}")
    
    def _get_daily_file_path(self) -> Path:
        """Get the CSV file path for today."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"{date_str}.csv"
    
    def _file_needs_header(self, file_path: Path) -> bool:
        """Check if file needs header row."""
        return not file_path.exists() or file_path.stat().st_size == 0
    
    def log_all_cameras(
        self,
        cameras: List[Dict],
        rain_features: Dict,
        tide_features: Dict
    ) -> int:
        """
        Log training data for all cameras.
        
        Args:
            cameras: List of camera dicts with 'CamId' and 'Coef' keys
            rain_features: Dict from RainFetcher.fetch_all_features()
            tide_features: Dict from TideFetcher.fetch_all_features()
            
        Returns:
            Number of rows logged
        """
        file_path = self._get_daily_file_path()
        needs_header = self._file_needs_header(file_path)
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows_logged = 0
        
        try:
            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.COLUMNS)
                
                if needs_header:
                    writer.writeheader()
                
                for camera in cameras:
                    row = {
                        "timestamp": timestamp,
                        "camera_id": camera.get("CamId", camera.get("id", "")),
                        "rain_prev_1h": rain_features.get("rain_prev_1h", 0.0),
                        "rain_prev_3h": rain_features.get("rain_prev_3h", 0.0),
                        "rain_next_1h": rain_features.get("rain_next_1h", 0.0),
                        "rain_next_3h": rain_features.get("rain_next_3h", 0.0),
                        "tide_now": tide_features.get("tide_now", 0.0),
                        "tide_prev_1h": tide_features.get("tide_prev_1h", 0.0),
                        "tide_next_1h": tide_features.get("tide_next_1h", 0.0),
                        "tide_next_3h": tide_features.get("tide_next_3h", 0.0),
                        "camera_coef": camera.get("Coef", 0.3)
                    }
                    writer.writerow(row)
                    rows_logged += 1
            
            logger.info(f"Logged {rows_logged} camera records to {file_path}")
            return rows_logged
            
        except Exception as e:
            logger.error(f"Failed to log training data: {e}")
            raise


# Global logger instance
_training_logger: TrainingDataLogger = None


def get_training_logger() -> TrainingDataLogger:
    """Get the global training data logger instance."""
    global _training_logger
    if _training_logger is None:
        _training_logger = TrainingDataLogger()
    return _training_logger
