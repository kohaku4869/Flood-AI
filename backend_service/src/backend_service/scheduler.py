"""
Background scheduler for periodic flood status checks and risk predictions.
Uses APScheduler with AsyncIOScheduler for FastAPI compatibility.
"""
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from datetime import datetime
from typing import Optional

from .logger import logger
from . import config
from .camera_service import get_camera_service
from .flood_state import get_flood_state_manager
from .ai_service import check_flood_status_for_all

# Global scheduler instance
_scheduler: Optional[AsyncIOScheduler] = None

# Global RiskRunner instance (lazy loaded)
_risk_runner = None


def get_risk_runner():
    """Get the global RiskRunner instance."""
    global _risk_runner
    if _risk_runner is None:
        from .RiskRunner import RiskRunner
        _risk_runner = RiskRunner()
    return _risk_runner


async def check_all_cameras_flood_status() -> None:
    """
    Background job to check flood status for all cameras.
    Updates the FloodStateManager with results.
    """
    flood_manager = get_flood_state_manager()
    
    # Skip if in test mode
    if flood_manager.test_mode:
        logger.info("Skipping flood check - test mode is active")
        return
    
    logger.info("Starting scheduled flood status check for all cameras")
    start_time = datetime.now()
    
    try:
        camera_service = get_camera_service()
        all_camera_ids = list(camera_service.cameras.keys())
        
        logger.info(f"Checking {len(all_camera_ids)} cameras...")
        
        # Call AI service to check all cameras
        results = await check_flood_status_for_all(all_camera_ids)
        
        # Update flood state manager
        for cam_id, result in results.items():
            flood_manager.update_camera_state(
                camera_id=cam_id,
                is_flooded=result.get('is_flooded', False),
                confidence=result.get('confidence', 0.0)
            )
        
        elapsed = (datetime.now() - start_time).total_seconds()
        flooded_count = flood_manager.get_flooded_count()
        logger.info(
            f"Flood check completed in {elapsed:.1f}s: "
            f"{flooded_count}/{len(all_camera_ids)} cameras flooded"
        )
        
        return results
        
    except Exception as e:
        logger.error(f"Error during scheduled flood check: {e}", exc_info=True)
        return {}


async def run_hourly_risk_job() -> None:
    """
    Hourly job to:
    1. Update coefficients from AI detection results
    2. Calculate risk predictions for 1-12 hours ahead
    3. Log training data to CSV
    """
    logger.info("Starting hourly risk job")
    start_time = datetime.now()
    
    try:
        # Step 1: Get AI detection results and update coefficients
        ai_results = await check_all_cameras_flood_status()
        
        if ai_results:
            risk_runner = get_risk_runner()
            risk_runner.batch_update_from_ai(ai_results)
        
        # Step 2: Calculate multi-hour predictions (1-12h)
        risk_runner = get_risk_runner()
        risk_runner.predict_multi_hour(hours=list(range(1, 13)))
        
        # Step 3: Log training data
        try:
            from .training_logger import get_training_logger
            from .WeatherService import RainFetcher, TideFetcher
            
            rain_fetcher = RainFetcher()
            tide_fetcher = TideFetcher(config.TIDE_DATA_PATH)
            
            rain_features = rain_fetcher.fetch_all_features()
            tide_features = tide_fetcher.fetch_all_features()
            
            cameras = list(get_camera_service().cameras.values())
            training_logger = get_training_logger()
            training_logger.log_all_cameras(cameras, rain_features, tide_features)
            
        except Exception as e:
            logger.error(f"Failed to log training data: {e}", exc_info=True)
        
        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(f"Hourly risk job completed in {elapsed:.1f}s")
        
    except Exception as e:
        logger.error(f"Error during hourly risk job: {e}", exc_info=True)


def get_scheduler() -> Optional[AsyncIOScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler() -> AsyncIOScheduler:
    """
    Initialize and configure the background scheduler.
    
    Returns:
        Configured AsyncIOScheduler instance
    """
    global _scheduler
    
    if _scheduler is not None:
        return _scheduler
    
    _scheduler = AsyncIOScheduler()
    
    # Add the flood check job (existing - runs every N minutes based on config)
    _scheduler.add_job(
        check_all_cameras_flood_status,
        trigger=IntervalTrigger(minutes=config.FLOOD_CHECK_INTERVAL_MINUTES),
        id='flood_check_job',
        name='Check flood status for all cameras',
        replace_existing=True
    )
    
    # Add the hourly risk job (new - runs every hour)
    risk_interval = getattr(config, 'RISK_CHECK_INTERVAL_HOURS', 1)
    _scheduler.add_job(
        run_hourly_risk_job,
        trigger=IntervalTrigger(hours=risk_interval),
        id='hourly_risk_job',
        name='Update coefficients and calculate predictions',
        replace_existing=True
    )
    
    logger.info(
        f"Scheduler configured: flood check every {config.FLOOD_CHECK_INTERVAL_MINUTES} minutes, "
        f"risk job every {risk_interval} hours"
    )
    
    return _scheduler


async def trigger_immediate_flood_check() -> None:
    """Trigger an immediate flood check (for startup or manual trigger)."""
    logger.info("Triggering immediate flood status check")
    await check_all_cameras_flood_status()


async def trigger_immediate_risk_job() -> None:
    """Trigger an immediate risk job (for startup or manual trigger)."""
    logger.info("Triggering immediate risk job")
    await run_hourly_risk_job()


def start_scheduler() -> None:
    """Start the scheduler."""
    global _scheduler
    if _scheduler and not _scheduler.running:
        _scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler() -> None:
    """Stop the scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
