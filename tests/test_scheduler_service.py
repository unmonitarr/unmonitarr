import time
import threading
from services import scheduler_service
from core import job_queue, job_handler
from unittest import mock

def test_scheduler_adds_enabled_jobs(monkeypatch):
    # Mock job_handler.get_enabled_apps to return both apps enabled
    monkeypatch.setattr(job_handler, "get_enabled_apps", lambda: ["sonarr", "radarr"])

    added_jobs = []
    def mock_add_job(job_type, triggered_by):
        added_jobs.append((job_type, triggered_by))

    monkeypatch.setattr(job_queue, "add_job", mock_add_job)

    # Run scheduler in a short-lived thread
    thread = threading.Thread(target=scheduler_service.start_scheduler, kwargs={"interval_seconds": 0.6}, daemon=True)
    thread.start()

    # Let it run briefly
    time.sleep(0.05)

    # Stop after one cycle (optional: add stop flag support to run_scheduler in future)
    assert ("sonarr", "scheduler") in added_jobs
    assert ("radarr", "scheduler") in added_jobs