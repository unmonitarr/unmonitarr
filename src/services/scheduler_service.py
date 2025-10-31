import time
import threading
from common.logger import get_logger
from core.job_queue import enqueue_job
from core.job_handler import get_enabled_apps
from core.config import Config

logger = get_logger("scheduler")

def scheduler_loop():
    logger.info(f"Scheduler started (every {Config.SLEEP_MINUTES} minutes)")
    while True:
        enabled_apps = get_enabled_apps()
        for app in enabled_apps:
            enqueue_job(app, payload={"triggered_by": "scheduler"})
        logger.debug(f"Scheduler sleeping for {Config.SLEEP_MINUTES} minutes...")
        time.sleep(Config.SLEEP_MINUTES * 60)

def start_scheduler():
    """Start the scheduler in a background thread"""
    scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True, name="scheduler")
    scheduler_thread.start()
    logger.info("Scheduler thread started")
    return scheduler_thread