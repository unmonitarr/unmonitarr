from common.logger import get_logger
from radarr.radarr_app import run_radarr
from sonarr.sonarr_app import run_job

class JobWorker:
    """
    Continuously processes jobs from the queue.
    Each job is a tuple: (job_type, triggered_by)
    """
    def __init__(self, job_queue, job_locks, logger):
        self.job_queue = job_queue
        self.job_locks = job_locks
        self.logger = logger

        # Map job types to their processing functions
        self.job_functions = {
            'radarr': run_radarr,
            'sonarr': run_job
        }

    def run(self):
        """
        Main processing loop - runs continuously until the program exits.
        Pulls jobs from the queue and processes them one at a time.
        """
        self.logger.info("Job worker started and waiting for jobs...")

        while True:
            try:
                # Block until a job is available in the queue
                job_type, triggered_by = self.job_queue.get()

                if job_type not in self.job_functions:
                    self.logger.error(f"Unknown job type: {job_type}")
                    continue

                # Acquire the lock for this job type to prevent concurrent execution
                lock = self.job_locks.get(job_type)
                if not lock:
                    self.logger.error(f"No lock found for job type: {job_type}")
                    continue

                with lock:
                    self.logger.info(f"Starting {job_type} job (triggered_by={triggered_by})")
                    try:
                        job_func = self.job_functions[job_type]
                        job_func()
                        self.logger.info(f"Completed {job_type} job (triggered_by={triggered_by})")
                    except Exception as e:
                        self.logger.error(f"Error processing {job_type} job: {e}", exc_info=True)

            except Exception as e:
                self.logger.error(f"Unexpected error in job worker: {e}", exc_info=True)