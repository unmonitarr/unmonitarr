import unittest
from core.job_queue import job_queue

class TestJobQueue(unittest.TestCase):
    def setUp(self):
        self.queue = job_queue
        while not self.queue.is_empty():
            self.queue.get_next_job()

    def test_enqueue_and_dequeue(self):
        self.queue.enqueue("test_job")
        job = self.queue.get_next_job()
        self.assertEqual(job["type"], "test_job")

    def test_is_empty(self):
        self.assertTrue(self.queue.is_empty())
        self.queue.enqueue("another_job")
        self.assertFalse(self.queue.is_empty())

if __name__ == '__main__':
    unittest.main()