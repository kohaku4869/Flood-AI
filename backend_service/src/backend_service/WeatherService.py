"""
Weather Service module.
Fetches rain and tide data for flood risk calculation.
Uses OpenWeather Free Tier APIs (Current Weather + 5 Day Forecast).
"""
import pandas as pd
import requests
from pathlib import Path
import os
from datetime import datetime, timedelta


class RainFetcher:
    """
    Fetches rainfall data from OpenWeather API.
    Uses Free Tier APIs: Current Weather + 5 Day/3 Hour Forecast.
    """
    
    def __init__(self, name_city="Ho Chi Minh City"):
        self.api_key = os.getenv("OPENWEATHER_API_KEY")
        self.name_city = name_city
        # Ho Chi Minh City coordinates
        self.lat = 10.8231
        self.lon = 106.6297
        self._cached_data = None
        self._cache_time = None
        self._cache_ttl = 600  # 10 minutes cache

    def _fetch_current_weather(self):
        """Fetch current weather data (free tier)."""
        url = (
            "https://api.openweathermap.org/data/2.5/weather"
            f"?lat={self.lat}&lon={self.lon}"
            "&units=metric"
            f"&appid={self.api_key}"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()

    def _fetch_forecast(self):
        """Fetch 5-day/3-hour forecast (free tier)."""
        url = (
            "https://api.openweathermap.org/data/2.5/forecast"
            f"?lat={self.lat}&lon={self.lon}"
            "&units=metric"
            f"&appid={self.api_key}"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()

    def _get_cached_or_fetch(self):
        """Get cached data or fetch new data."""
        now = datetime.now()
        if (self._cached_data is None or 
            self._cache_time is None or 
            (now - self._cache_time).seconds > self._cache_ttl):
            
            current = self._fetch_current_weather()
            forecast = self._fetch_forecast()
            
            self._cached_data = {
                "current": current,
                "forecast": forecast
            }
            self._cache_time = now
        
        return self._cached_data

    def fetch(self, time_context):
        """
        Fetch total rainfall in a 3-hour window ending at (now + time_context).
        
        Args:
            time_context: Hours offset from current time (0, 1, 2, 3, ...)
            
        Returns:
            dict with 'total_rain_3h' (mm), 'timestamp', 'hours_covered'
        """
        from datetime import timezone
        
        data = self._get_cached_or_fetch()
        current = data["current"]
        forecast = data["forecast"]
        
        now = datetime.now(timezone.utc)
        target_time = now + timedelta(hours=time_context)
        
        # Current rain (last 1h or 3h)
        current_rain_1h = current.get("rain", {}).get("1h", 0.0)
        current_rain_3h = current.get("rain", {}).get("3h", current_rain_1h * 3)
        
        # If time_context is 0-2, use current data
        if time_context <= 2:
            return {
                "total_rain_3h": round(current_rain_3h, 2),
                "timestamp": now,
                "hours_covered": 3,
                "note": "Using current weather data"
            }
        
        # For future hours, find the closest forecast entry
        # Forecast is in 3-hour intervals
        forecast_list = forecast.get("list", [])
        
        total_rain = 0.0
        hours_covered = 0
        
        for entry in forecast_list:
            entry_time = datetime.fromtimestamp(entry["dt"], tz=timezone.utc)
            hours_diff = (entry_time - now).total_seconds() / 3600
            
            # Find entries within our window
            window_start = time_context - 3
            window_end = time_context
            
            if window_start <= hours_diff <= window_end + 3:
                rain_3h = entry.get("rain", {}).get("3h", 0.0)
                total_rain += rain_3h
                hours_covered += 3
            
            if hours_diff > window_end + 3:
                break
        
        return {
            "total_rain_3h": round(total_rain, 2),
            "timestamp": now,
            "hours_covered": hours_covered
        }

    def fetch_all_features(self):
        """
        Fetch all rain features needed for training data logging.
        
        Returns:
            dict with rain_prev_1h, rain_prev_3h, rain_next_1h, rain_next_3h
        """
        from datetime import timezone
        
        data = self._get_cached_or_fetch()
        current = data["current"]
        forecast = data["forecast"]
        
        # Current rain (estimate for past)
        current_rain_1h = current.get("rain", {}).get("1h", 0.0)
        current_rain_3h = current.get("rain", {}).get("3h", current_rain_1h * 3)
        
        # Future rain from forecast
        forecast_list = forecast.get("list", [])
        
        rain_next_1h = 0.0
        rain_next_3h = 0.0
        
        if len(forecast_list) >= 1:
            # First forecast entry (next 3 hours)
            rain_next_3h = forecast_list[0].get("rain", {}).get("3h", 0.0)
            # Estimate next 1h as 1/3 of next 3h
            rain_next_1h = rain_next_3h / 3
        
        return {
            "rain_prev_1h": round(current_rain_1h, 2),
            "rain_prev_3h": round(current_rain_3h, 2),
            "rain_next_1h": round(rain_next_1h, 2),
            "rain_next_3h": round(rain_next_3h, 2),
            "timestamp": datetime.now(timezone.utc)
        }


class TideFetcher:
    """
    Fetches tide data from local CSV file.
    CSV format: Date,Month,0,1,2,...,23 (hours as columns)
    """
    
    def __init__(self, data_path: Path):
        self.data = pd.read_csv(data_path)

    def _get_tide(self, month, date, hour):
        """
        Get tide level for specific month, date, and hour.
        
        Args:
            month: Month (1-12)
            date: Day of month (1-31)
            hour: Hour of day (0-23)
        """
        # CSV has columns: Date, Month, 0, 1, 2, ..., 23
        row = self.data[
            (self.data["Month"] == month) &
            (self.data["Date"] == date)
        ]

        if row.empty:
            return None
        
        # Hour is a column name (as string or int)
        hour_col = str(hour)
        if hour_col not in row.columns:
            return None

        value = row.iloc[0][hour_col]
        
        # Handle potential non-numeric values
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def fetch(self, time_context):
        """
        Fetch tide level at target time and calculate change from previous hour.
        
        Args:
            time_context: Hours offset from current time
            
        Returns:
            dict with 'tide_now' (m), 'tide_delta' (m, positive change only)
        """
        # Calculate target time using proper datetime operations
        target_time = datetime.now() + timedelta(hours=time_context)
        
        # Get tide at target time
        tide_now = self._get_tide(target_time.month, target_time.day, target_time.hour)
        
        # Calculate previous hour using timedelta (handles day/month/year boundaries)
        prev_time = target_time - timedelta(hours=1)
        tide_prev = self._get_tide(prev_time.month, prev_time.day, prev_time.hour)
        
        # Use defaults if data not found (avoid raising errors)
        if tide_now is None:
            tide_now = 1.0  # Default tide level
        if tide_prev is None:
            tide_prev = tide_now
        
        return {
            "tide_now": tide_now,
            "tide_delta": max(tide_now - tide_prev, 0),
        }

    def fetch_all_features(self):
        """
        Fetch all tide features needed for training data logging.
        
        Returns:
            dict with tide_now, tide_prev_1h, tide_next_1h, tide_next_3h
        """
        now = datetime.now()
        
        # Current tide
        tide_now = self._get_tide(now.month, now.day, now.hour)
        
        # Previous hour
        prev_1h = now - timedelta(hours=1)
        tide_prev_1h = self._get_tide(prev_1h.month, prev_1h.day, prev_1h.hour)
        
        # Next hour
        next_1h = now + timedelta(hours=1)
        tide_next_1h = self._get_tide(next_1h.month, next_1h.day, next_1h.hour)
        
        # 3 hours ahead
        next_3h = now + timedelta(hours=3)
        tide_next_3h = self._get_tide(next_3h.month, next_3h.day, next_3h.hour)
        
        return {
            "tide_now": tide_now or 1.0,
            "tide_prev_1h": tide_prev_1h or 1.0,
            "tide_next_1h": tide_next_1h or 1.0,
            "tide_next_3h": tide_next_3h or 1.0,
            "timestamp": now
        }