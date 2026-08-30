import unittest

from core.job_queue import JobQueueWrapper


class TestJobQueueWrapper(unittest.TestCase):
    """Tests for the JobQueueWrapper class itself.

    Uses a fresh instance rather than the module-level `job_queue`, because importing
    core.job_queue starts a real worker thread that would consume anything put on the
    global queue. The module-level add_job/enqueue_job helpers are covered by
    tests/test_queue.py.
    """

    def setUp(self):
        self.queue = JobQueueWrapper()

    def test_new_queue_is_empty(self):
        self.assertTrue(self.queue.empty())
        self.assertTrue(self.queue.is_empty())
        self.assertEqual(len(self.queue), 0)

    def test_put_and_get_roundtrip(self):
        self.queue.put(("sonarr", "webhook"))
        self.assertFalse(self.queue.empty())
        self.assertEqual(self.queue.get(), ("sonarr", "webhook"))
        self.assertTrue(self.queue.empty())

    def test_enqueue_is_an_alias_for_put(self):
        self.queue.enqueue(("radarr", "scheduler"))
        self.assertEqual(len(self.queue), 1)
        self.assertEqual(self.queue.get(), ("radarr", "scheduler"))

    def test_is_empty_matches_empty(self):
        self.assertEqual(self.queue.is_empty(), self.queue.empty())
        self.queue.put(("sonarr", "webhook"))
        self.assertEqual(self.queue.is_empty(), self.queue.empty())
        self.assertFalse(self.queue.is_empty())

    def test_len_tracks_pending_jobs(self):
        for i in range(3):
            self.queue.put(("sonarr", f"trigger-{i}"))
        self.assertEqual(len(self.queue), 3)
        self.queue.get()
        self.assertEqual(len(self.queue), 2)

    def test_fifo_order(self):
        self.queue.put(("sonarr", "webhook"))
        self.queue.put(("radarr", "scheduler"))
        self.assertEqual(self.queue.get(), ("sonarr", "webhook"))
        self.assertEqual(self.queue.get(), ("radarr", "scheduler"))

    def test_clear_drains_the_queue(self):
        for i in range(5):
            self.queue.put(("sonarr", f"trigger-{i}"))
        self.queue.clear()
        self.assertTrue(self.queue.empty())
        self.assertEqual(len(self.queue), 0)

    def test_clear_on_empty_queue_is_a_noop(self):
        self.queue.clear()  # must not block or raise
        self.assertTrue(self.queue.empty())


if __name__ == "__main__":
    unittest.main()
