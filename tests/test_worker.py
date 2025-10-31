import unittest
from unittest.mock import MagicMock, patch
from core.job_worker import JobWorker
import threading
from queue import Queue, Empty
import time

class TestJobWorker(unittest.TestCase):
    def setUp(self):
        self.mock_logger = MagicMock()
        self.real_queue = Queue()
        self.job_locks = {
            'radarr': threading.Lock(),
            'sonarr': threading.Lock()
        }

    @patch('core.job_worker.run_radarr')
    def test_worker_processes_radarr_job(self, mock_run_radarr):
        """Test that the worker correctly processes a radarr job"""
        # Add a radarr job to the queue
        self.real_queue.put(('radarr', 'webhook'))

        worker = JobWorker(self.real_queue, self.job_locks, self.mock_logger)

        # Run worker in a thread with a timeout
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()

        # Wait for job to be processed (with timeout)
        time.sleep(0.5)

        # Verify radarr job was executed
        mock_run_radarr.assert_called_once()
        self.mock_logger.info.assert_any_call('Starting radarr job (triggered_by=webhook)')

    @patch('core.job_worker.run_job')
    def test_worker_processes_sonarr_job(self, mock_run_job):
        """Test that the worker correctly processes a sonarr job"""
        # Add a sonarr job to the queue
        self.real_queue.put(('sonarr', 'scheduler'))

        worker = JobWorker(self.real_queue, self.job_locks, self.mock_logger)

        # Run worker in a thread with a timeout
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()

        # Wait for job to be processed
        time.sleep(0.5)

        # Verify sonarr job was executed
        mock_run_job.assert_called_once()
        self.mock_logger.info.assert_any_call('Starting sonarr job (triggered_by=scheduler)')

    def test_worker_handles_unknown_job_type(self):
        """Test that the worker handles unknown job types gracefully"""
        # Add an unknown job type to the queue
        self.real_queue.put(('unknown', 'webhook'))

        worker = JobWorker(self.real_queue, self.job_locks, self.mock_logger)

        # Run worker in a thread
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()

        # Wait for job to be processed
        time.sleep(0.5)

        # Verify error was logged
        self.mock_logger.error.assert_any_call('Unknown job type: unknown')

    @patch('core.job_worker.run_radarr')
    def test_worker_handles_job_exception(self, mock_run_radarr):
        """Test that the worker handles exceptions in job functions"""
        # Make the radarr job raise an exception
        mock_run_radarr.side_effect = RuntimeError("Test error")

        # Add a radarr job
        self.real_queue.put(('radarr', 'scheduler'))

        worker = JobWorker(self.real_queue, self.job_locks, self.mock_logger)

        # Run worker in a thread
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()

        # Wait for job to be processed
        time.sleep(0.5)

        # Verify error was logged but worker continued
        self.assertTrue(any('Error processing radarr job' in str(call)
                          for call in self.mock_logger.error.call_args_list))

    @patch('core.job_worker.run_radarr')
    @patch('core.job_worker.run_job')
    def test_worker_processes_multiple_jobs(self, mock_run_job, mock_run_radarr):
        """Test that the worker processes multiple jobs in sequence"""
        # Add multiple jobs
        self.real_queue.put(('sonarr', 'webhook'))
        self.real_queue.put(('radarr', 'scheduler'))
        self.real_queue.put(('sonarr', 'scheduler'))

        worker = JobWorker(self.real_queue, self.job_locks, self.mock_logger)

        # Run worker in a thread
        worker_thread = threading.Thread(target=worker.run, daemon=True)
        worker_thread.start()

        # Wait for all jobs to be processed
        time.sleep(1.0)

        # Verify all jobs were executed
        self.assertEqual(mock_run_job.call_count, 2)
        self.assertEqual(mock_run_radarr.call_count, 1)

if __name__ == '__main__':
    unittest.main()