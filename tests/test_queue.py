import unittest
from unittest.mock import patch, MagicMock
from core.job_queue import job_queue, add_job, enqueue_job

class TestJobQueue(unittest.TestCase):
    def setUp(self):
        job_queue.clear()

    def test_add_job_queues_tuple(self):
        """Test that add_job adds a (job_type, triggered_by) tuple to the queue"""
        add_job("sonarr", triggered_by="webhook")
        self.assertEqual(len(job_queue), 1)

        # Get the item from the queue
        job_type, triggered_by = job_queue.get()
        self.assertEqual(job_type, "sonarr")
        self.assertEqual(triggered_by, "webhook")

    def test_add_multiple_jobs(self):
        """Test that multiple jobs can be queued"""
        add_job("sonarr", triggered_by="webhook")
        add_job("radarr", triggered_by="scheduler")
        add_job("sonarr", triggered_by="scheduler")

        # All three jobs should be in the queue
        self.assertEqual(len(job_queue), 3)

    def test_add_job_with_unknown_type(self):
        """Test that add_job handles unknown job types gracefully"""
        add_job("unknown", triggered_by="webhook")

        # Job should not be added to the queue
        self.assertTrue(job_queue.empty())

    def test_enqueue_job_defaults_to_scheduler(self):
        """Test that enqueue_job defaults triggered_by to 'scheduler'"""
        enqueue_job("radarr")

        job_type, triggered_by = job_queue.get()
        self.assertEqual(job_type, "radarr")
        self.assertEqual(triggered_by, "scheduler")

    def test_enqueue_job_with_payload(self):
        """Test that enqueue_job accepts payload with triggered_by"""
        enqueue_job("sonarr", payload={"triggered_by": "webhook"})

        job_type, triggered_by = job_queue.get()
        self.assertEqual(job_type, "sonarr")
        self.assertEqual(triggered_by, "webhook")

    def test_queue_fifo_order(self):
        """Test that jobs are processed in FIFO order"""
        add_job("sonarr", triggered_by="webhook")
        add_job("radarr", triggered_by="scheduler")
        add_job("sonarr", triggered_by="scheduler")

        # Get jobs in order
        job1_type, job1_trigger = job_queue.get()
        job2_type, job2_trigger = job_queue.get()
        job3_type, job3_trigger = job_queue.get()

        self.assertEqual(job1_type, "sonarr")
        self.assertEqual(job1_trigger, "webhook")
        self.assertEqual(job2_type, "radarr")
        self.assertEqual(job2_trigger, "scheduler")
        self.assertEqual(job3_type, "sonarr")
        self.assertEqual(job3_trigger, "scheduler")

if __name__ == "__main__":
    unittest.main()
