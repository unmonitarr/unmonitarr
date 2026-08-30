import unittest
from unittest.mock import patch

import main


class TestMain(unittest.TestCase):
    """main() ends with a blocking Flask server, so every start_* call is patched.

    Patching is done at the `main` namespace because main.py imports the functions
    directly (`from services.webhook_service import start_webhook_server`).
    """

    def _patched_main(self):
        return (
            patch.object(main, "setup_logging"),
            patch.object(main, "initialise_environment", return_value=["sonarr", "radarr"]),
            patch.object(main, "start_job_queue"),
            patch.object(main, "start_scheduler"),
            patch.object(main, "start_webhook_server"),
        )

    def test_starts_every_service(self):
        patches = self._patched_main()
        with patches[0] as setup_logging, patches[1] as init_env, \
             patches[2] as start_queue, patches[3] as start_sched, \
             patches[4] as start_webhook:
            main.main()

        setup_logging.assert_called_once()
        init_env.assert_called_once()
        start_queue.assert_called_once()
        start_sched.assert_called_once()
        start_webhook.assert_called_once()

    def test_webhook_server_starts_last(self):
        # The webhook server blocks, so anything started after it would never run
        order = []
        patches = self._patched_main()
        with patches[0], \
             patches[1] as init_env, \
             patch.object(main, "start_job_queue", side_effect=lambda: order.append("queue")), \
             patch.object(main, "start_scheduler", side_effect=lambda: order.append("scheduler")), \
             patch.object(main, "start_webhook_server", side_effect=lambda: order.append("webhook")):
            init_env.return_value = ["sonarr"]
            main.main()

        self.assertEqual(order, ["queue", "scheduler", "webhook"])

    def test_still_starts_services_with_no_apps_enabled(self):
        # initialise_environment only warns when nothing is enabled; main carries on so
        # the health endpoint stays up and config can be fixed without a rebuild
        patches = self._patched_main()
        with patches[0], patches[1] as init_env, patches[2] as start_queue, \
             patches[3] as start_sched, patches[4] as start_webhook:
            init_env.return_value = []
            main.main()

        start_queue.assert_called_once()
        start_sched.assert_called_once()
        start_webhook.assert_called_once()

    def test_propagates_startup_failure(self):
        patches = self._patched_main()
        with patches[0], patches[1], \
             patch.object(main, "start_job_queue", side_effect=RuntimeError("boom")), \
             patches[3] as start_sched, patches[4] as start_webhook:
            with self.assertRaises(RuntimeError):
                main.main()

        start_sched.assert_not_called()
        start_webhook.assert_not_called()


if __name__ == "__main__":
    unittest.main()
