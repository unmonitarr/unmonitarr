__all__ = ["job_queue", "job_locks", "add_job", "worker_thread", "enqueue_job", "start_job_queue", "add_job_to_queue"]
from common.logger import get_logger
import threading
from queue import Queue
from core.job_worker import JobWorker  # Import the job processing class

logger = get_logger(__name__)

class JobQueueWrapper:
    def __init__(self):
        self._queue = Queue()

    def put(self, item):
        self._queue.put(item)

    def get(self):
        return self._queue.get()

    def empty(self):
        return self._queue.empty()

    def enqueue(self, item):
        self._queue.put(item)

    def is_empty(self):
        return self._queue.empty()

    def __len__(self):
        return self._queue.qsize()

    def clear(self):
        while not self._queue.empty():
            self._queue.get()

# Global queue used to store incoming jobs for processing
job_queue = JobQueueWrapper()

# Locks to ensure only one job of each type runs at a time
job_locks = {
    'sonarr': threading.Lock(),
    'radarr': threading.Lock()
}

def add_job(job_type, triggered_by="scheduler"):
    """
    Add a job to the queue for processing.

    Args:
        job_type (str): Type of the job ('sonarr' or 'radarr').
        triggered_by (str): Source of the trigger ('scheduler' or 'webhook').
    """
    if job_type not in job_locks:
        logger.warning(f"Unknown job type: {job_type}")
        return

    logger.debug(f"Queuing job: {job_type} (triggered_by={triggered_by})")
    job_queue.put((job_type, triggered_by))


# Start the job worker thread to process jobs from the queue
worker = JobWorker(job_queue, job_locks, logger)
worker_thread = threading.Thread(target=worker.run, daemon=True)
worker_thread.start()


# Expose these for use in test files and other modules
def enqueue_job(job_type, payload=None):
    triggered_by = payload.get("triggered_by", "scheduler") if payload else "scheduler"
    add_job(job_type, triggered_by=triggered_by)

def start_job_queue():
    # Already started above during module import, but included here for consistency/testing
    return worker_thread

# Alias for backward compatibility with older imports
add_job_to_queue = enqueue_job