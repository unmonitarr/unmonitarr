import threading
import unittest
from queue import Queue
from unittest.mock import MagicMock, patch

from core.job_worker import JobWorker


class TestJobWorker(unittest.TestCase):
    """Drives JobWorker.process_next() directly, so no threads or sleeps are needed."""

    def setUp(self):
        self.logger = MagicMock()
        self.queue = Queue()
        self.locks = {"radarr": threading.Lock(), "sonarr": threading.Lock()}

    def worker(self):
        return JobWorker(self.queue, self.locks, self.logger)

    def drain(self, worker):
        while not self.queue.empty():
            worker.process_next()

    @patch("core.job_worker.run_radarr")
    def test_processes_radarr_job(self, run_radarr):
        self.queue.put(("radarr", "webhook"))
        self.drain(self.worker())
        run_radarr.assert_called_once()
        self.logger.info.assert_any_call("Starting radarr job (triggered_by=webhook)")
        self.logger.info.assert_any_call("Completed radarr job (triggered_by=webhook)")

    @patch("core.job_worker.run_sonarr")
    def test_processes_sonarr_job(self, run_sonarr):
        self.queue.put(("sonarr", "scheduler"))
        self.drain(self.worker())
        run_sonarr.assert_called_once()
        self.logger.info.assert_any_call("Starting sonarr job (triggered_by=scheduler)")

    def test_unknown_job_type_is_logged(self):
        self.queue.put(("unknown", "webhook"))
        self.drain(self.worker())
        self.logger.error.assert_any_call("Unknown job type: unknown")

    @patch("core.job_worker.run_radarr")
    def test_missing_lock_is_logged(self, run_radarr):
        del self.locks["radarr"]
        self.queue.put(("radarr", "webhook"))
        self.drain(self.worker())
        run_radarr.assert_not_called()
        self.logger.error.assert_any_call("No lock found for job type: radarr")

    @patch("core.job_worker.run_radarr")
    def test_job_exception_is_logged_and_lock_released(self, run_radarr):
        run_radarr.side_effect = RuntimeError("Test error")
        self.queue.put(("radarr", "scheduler"))
        self.drain(self.worker())
        self.assertTrue(any("Error processing radarr job" in str(c) for c in self.logger.error.call_args_list))
        self.assertFalse(self.locks["radarr"].locked())

    @patch("core.job_worker.run_radarr")
    @patch("core.job_worker.run_sonarr")
    def test_processes_multiple_jobs_in_order(self, run_sonarr, run_radarr):
        order = []
        run_sonarr.side_effect = lambda: order.append("sonarr")
        run_radarr.side_effect = lambda: order.append("radarr")
        for job in (("sonarr", "webhook"), ("radarr", "scheduler"), ("sonarr", "scheduler")):
            self.queue.put(job)
        self.drain(self.worker())
        self.assertEqual(order, ["sonarr", "radarr", "sonarr"])

    @patch("core.job_worker.run_radarr")
    def test_run_loop_survives_unexpected_errors(self, run_radarr):
        """run() keeps going if process_next itself raises."""
        worker = self.worker()
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            raise SystemExit  # stop the loop on the second call

        with patch.object(worker, "process_next", side_effect=flaky):
            with self.assertRaises(SystemExit):
                worker.run()
        self.assertEqual(calls["n"], 2)
        self.assertTrue(any("Unexpected error in job worker" in str(c) for c in self.logger.error.call_args_list))


if __name__ == "__main__":
    unittest.main()
