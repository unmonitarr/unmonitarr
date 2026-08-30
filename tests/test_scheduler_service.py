import unittest
from unittest.mock import patch

from services import scheduler_service


class _StopLoop(Exception):
    """Used to break scheduler_loop's infinite while loop deterministically."""


class TestSchedulerLoop(unittest.TestCase):
    """scheduler_loop runs forever, so time.sleep is patched to raise after one cycle.

    Patching at the scheduler_service namespace matters: the module does
    `from core.job_queue import enqueue_job`, so patching core.job_queue.enqueue_job
    would not affect the already-bound reference.
    """

    def _run_one_cycle(self, enabled_apps):
        with patch.object(scheduler_service, "get_enabled_apps", return_value=enabled_apps), \
             patch.object(scheduler_service, "enqueue_job") as mock_enqueue, \
             patch.object(scheduler_service.time, "sleep", side_effect=_StopLoop):
            with self.assertRaises(_StopLoop):
                scheduler_service.scheduler_loop()
        return mock_enqueue

    def test_queues_a_job_for_each_enabled_app(self):
        mock_enqueue = self._run_one_cycle(["sonarr", "radarr"])

        self.assertEqual(mock_enqueue.call_count, 2)
        mock_enqueue.assert_any_call("sonarr", payload={"triggered_by": "scheduler"})
        mock_enqueue.assert_any_call("radarr", payload={"triggered_by": "scheduler"})

    def test_queues_nothing_when_no_apps_enabled(self):
        mock_enqueue = self._run_one_cycle([])
        mock_enqueue.assert_not_called()

    def test_only_queues_enabled_apps(self):
        mock_enqueue = self._run_one_cycle(["sonarr"])
        mock_enqueue.assert_called_once_with("sonarr", payload={"triggered_by": "scheduler"})

    def test_sleeps_for_configured_interval(self):
        with patch.object(scheduler_service, "get_enabled_apps", return_value=[]), \
             patch.object(scheduler_service, "enqueue_job"), \
             patch.object(scheduler_service.Config, "SLEEP_MINUTES", 30), \
             patch.object(scheduler_service.time, "sleep", side_effect=_StopLoop) as mock_sleep:
            with self.assertRaises(_StopLoop):
                scheduler_service.scheduler_loop()

        mock_sleep.assert_called_once_with(30 * 60)


class TestStartScheduler(unittest.TestCase):
    def test_starts_a_daemon_thread(self):
        with patch.object(scheduler_service, "scheduler_loop") as mock_loop:
            thread = scheduler_service.start_scheduler()
            thread.join(timeout=2)

        self.assertTrue(thread.daemon, "Scheduler must be a daemon so it can't block shutdown")
        self.assertEqual(thread.name, "scheduler")
        mock_loop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
