import unittest
from unittest.mock import patch, MagicMock
from services.webhook_service import app
from core.job_queue import job_queue, add_job_to_queue

class TestWebhookService(unittest.TestCase):
    def setUp(self):
        self.test_queue = job_queue

    @patch('services.webhook_service.add_job_to_queue')
    def test_trigger_sonarr(self, mock_add_job):
        with app.test_client() as client:
            response = client.post('/trigger/sonarr')
            self.assertEqual(response.status_code, 202)
            mock_add_job.assert_called_with('sonarr', 'webhook')

    @patch('services.webhook_service.add_job_to_queue')
    def test_trigger_radarr(self, mock_add_job):
        with app.test_client() as client:
            response = client.post('/trigger/radarr')
            self.assertEqual(response.status_code, 202)
            mock_add_job.assert_called_with('radarr', 'webhook')

    def test_trigger_invalid(self):
        with app.test_client() as client:
            response = client.post('/trigger/invalidapp')
            self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()