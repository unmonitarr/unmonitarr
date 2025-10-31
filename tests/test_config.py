import pytest
from core import config

def test_config_structure():
    # Ensure internal config data is a dictionary
    assert isinstance(config.CONFIG.config.get(), dict), "CONFIG.get() should return a dictionary"

    # Check presence of expected top-level keys
    expected_keys = ['apps', 'settings']
    for key in expected_keys:
        assert key in config.CONFIG.config.get(), f"Missing expected key: {key} in CONFIG"

    # Example: check app toggles exist and are boolean
    assert isinstance(config.CONFIG.config.get('apps', {}).get('sonarr'), bool), "Sonarr config must be a boolean"
    assert isinstance(config.CONFIG.config.get('apps', {}).get('radarr'), bool), "Radarr config must be a boolean"

    # Check settings block includes sleep_time as integer
    sleep_time = config.CONFIG.config.get('settings', {}).get('sleep_time')
    assert isinstance(sleep_time, int), "sleep_time must be an integer"

def test_sleep_time_positive():
    sleep_time = config.CONFIG.config.get("settings", {}).get("sleep_time")
    assert sleep_time > 0, "sleep_time must be a positive integer"