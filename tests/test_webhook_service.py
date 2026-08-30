import unittest
from unittest.mock import patch

from services.webhook_service import app


class TestWebhookService(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("services.webhook_service.add_job")
    def test_trigger_sonarr(self, mock_add_job):
        response = self.client.post("/trigger/sonarr")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"status": "queued", "job": "sonarr"})
        mock_add_job.assert_called_once_with("sonarr", triggered_by="webhook")

    @patch("services.webhook_service.add_job")
    def test_trigger_radarr(self, mock_add_job):
        response = self.client.post("/trigger/radarr")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json(), {"status": "queued", "job": "radarr"})
        mock_add_job.assert_called_once_with("radarr", triggered_by="webhook")

    @patch("services.webhook_service.add_job")
    def test_unknown_app_is_not_routed(self, mock_add_job):
        # There is no /trigger/<app> catch-all, so an unknown app is simply Not Found
        response = self.client.post("/trigger/invalidapp")
        self.assertEqual(response.status_code, 404)
        mock_add_job.assert_not_called()

    @patch("services.webhook_service.add_job")
    def test_get_is_not_allowed_on_triggers(self, mock_add_job):
        response = self.client.get("/trigger/sonarr")
        self.assertEqual(response.status_code, 405)
        mock_add_job.assert_not_called()

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "healthy", "service": "unmonitarr"})


if __name__ == "__main__":
    unittest.main()
