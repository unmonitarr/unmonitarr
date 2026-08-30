import importlib
import os
import unittest
from unittest.mock import patch


class TestEnvHelpers(unittest.TestCase):
    """Tests for env_bool and env_int in core.config."""

    def setUp(self):
        from core.config import env_bool, env_int
        self.env_bool = env_bool
        self.env_int = env_int

    def test_env_bool_truthy_values(self):
        for value in ("1", "true", "TRUE", "yes", "Yes", "on", "ON"):
            with patch.dict(os.environ, {"TEST_FLAG": value}):
                self.assertTrue(self.env_bool("TEST_FLAG"), f"{value!r} should be True")

    def test_env_bool_falsy_values(self):
        for value in ("0", "false", "no", "off", "", "banana"):
            with patch.dict(os.environ, {"TEST_FLAG": value}):
                self.assertFalse(self.env_bool("TEST_FLAG"), f"{value!r} should be False")

    def test_env_bool_uses_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(self.env_bool("MISSING_FLAG", "1"))
            self.assertFalse(self.env_bool("MISSING_FLAG", "0"))
            self.assertFalse(self.env_bool("MISSING_FLAG"))

    def test_env_int_parses_values(self):
        for value, expected in (("30", 30), ("0", 0), ("-60", -60)):
            with patch.dict(os.environ, {"TEST_INT": value}):
                self.assertEqual(self.env_int("TEST_INT"), expected)

    def test_env_int_falls_back_on_garbage(self):
        with patch.dict(os.environ, {"TEST_INT": "not-a-number"}):
            self.assertEqual(self.env_int("TEST_INT", "120"), 120)

    def test_env_int_uses_default_when_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.env_int("MISSING_INT", "42"), 42)


class TestConfigDefaults(unittest.TestCase):
    """Config reads the environment at import time, so these tests reload the module.

    Always reloaded again on cleanup so a stale Config can't leak into other tests.
    """

    def _reload_with_env(self, env):
        from core import config as config_module
        with patch.dict(os.environ, env, clear=True):
            importlib.reload(config_module)
        self.addCleanup(importlib.reload, config_module)
        return config_module.Config

    def test_defaults_match_documented_values(self):
        cfg = self._reload_with_env({})

        self.assertEqual(cfg.TZ, "UTC")
        self.assertEqual(cfg.SLEEP_MINUTES, 30)
        self.assertEqual(cfg.DELAY_MINUTES, 120)
        self.assertEqual(cfg.AUTO_TAG_NAME, "auto-unmonitored")
        self.assertEqual(cfg.IGNORE_TAG_NAME, "ignore")
        self.assertTrue(cfg.SKIP_IF_FILE)
        self.assertTrue(cfg.DRY_RUN, "DRY_RUN must default on - safety first")
        self.assertEqual(cfg.LOG_LEVEL, "INFO")

        self.assertTrue(cfg.ENABLE_RADARR)
        self.assertEqual(cfg.RADARR_URL, "")
        self.assertEqual(cfg.PREFERRED_RELEASE, "either")
        self.assertFalse(cfg.IGNORE_INCINEMAS)
        self.assertEqual(cfg.RADARR_REMONITOR_WINDOW_DAYS, 30)

        self.assertTrue(cfg.ENABLE_SONARR)
        self.assertEqual(cfg.SONARR_URL, "")
        self.assertFalse(cfg.SEASON_PACK_MODE)
        self.assertEqual(cfg.SEASON_PACK_MODE_TAG, "season-pack")
        self.assertFalse(cfg.SONARR_REFRESH_TBA)
        self.assertEqual(cfg.SONARR_REMONITOR_WINDOW_DAYS, 14)

    def test_environment_overrides_are_applied(self):
        cfg = self._reload_with_env({
            "TZ": "Australia/Melbourne",
            "SLEEP_MINUTES": "5",
            "DELAY_MINUTES": "-60",
            "DRY_RUN": "0",
            "LOG_LEVEL": "debug",
            "SONARR_REFRESH_TBA": "1",
            "PREFERRED_RELEASE": "DIGITAL",
        })

        self.assertEqual(cfg.TZ, "Australia/Melbourne")
        self.assertEqual(cfg.SLEEP_MINUTES, 5)
        self.assertEqual(cfg.DELAY_MINUTES, -60, "negative delays are supported since v0.11.3")
        self.assertFalse(cfg.DRY_RUN)
        self.assertEqual(cfg.LOG_LEVEL, "DEBUG", "LOG_LEVEL is upper-cased")
        self.assertTrue(cfg.SONARR_REFRESH_TBA)
        self.assertEqual(cfg.PREFERRED_RELEASE, "digital", "PREFERRED_RELEASE is lower-cased")

    def test_urls_have_trailing_slash_stripped(self):
        cfg = self._reload_with_env({
            "SONARR_URL": "http://sonarr:8989/",
            "RADARR_URL": "http://radarr:7878///",
        })
        self.assertEqual(cfg.SONARR_URL, "http://sonarr:8989")
        self.assertEqual(cfg.RADARR_URL, "http://radarr:7878")


class TestConfigAccessors(unittest.TestCase):
    """Config exposes dict-style access via __getitem__ / __contains__."""

    def setUp(self):
        from core.config import CONFIG
        self.config = CONFIG

    def test_getitem_returns_attribute(self):
        self.assertEqual(self.config["DELAY_MINUTES"], self.config.DELAY_MINUTES)

    def test_getitem_raises_for_unknown_key(self):
        with self.assertRaises(AttributeError):
            self.config["NOPE"]

    def test_contains(self):
        self.assertIn("SONARR_REFRESH_TBA", self.config)
        self.assertNotIn("NOPE", self.config)


if __name__ == "__main__":
    unittest.main()
