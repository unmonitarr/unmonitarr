import logging
from common.logging_setup import setup_logging
from core.job_handler import initialise_environment
from core.job_queue import start_job_queue
from services.scheduler_service import start_scheduler
from services.webhook_service import start_webhook_server

def main():
    # Setup logging
    setup_logging()
    logger = logging.getLogger("main")
    logger.info("🔧 Initialising Unmonitarr...")

    # Initialise app configuration and environment
    enabled_apps = initialise_environment()
    logger.info(f"Enabled apps: {enabled_apps}")

    # Start job queue processor thread
    start_job_queue()

    # Start scheduler service thread
    start_scheduler()

    # Start webhook server (blocking)
    logger.info("Starting webhook server on port 5099...")
    start_webhook_server()

if __name__ == "__main__":
    main()
