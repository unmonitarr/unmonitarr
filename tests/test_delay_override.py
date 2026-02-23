import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch


class TestGetDelayOverride(unittest.TestCase):
    """Tests for _get_delay_override in both radarr_app and sonarr_app."""

    def _get_radarr_fn(self):
        from radarr.radarr_app import _get_delay_override
        return _get_delay_override

    def _get_sonarr_fn(self):
        from sonarr.sonarr_app import _get_delay_override
        return _get_delay_override

    def _make_id_to_label(self, labels):
        """Build id_to_label dict from a list of label strings (ids are 1-indexed)."""
        return {i + 1: label for i, label in enumerate(labels)}

    # --- radarr ---

    def test_radarr_single_match_returns_timedelta(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["delayby_120"])
        result = fn([1], id_to_label, "Test Movie")
        self.assertEqual(result, timedelta(minutes=120))

    def test_radarr_negative_value_returns_timedelta(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["delayby_-60"])
        result = fn([1], id_to_label, "Test Movie")
        self.assertEqual(result, timedelta(minutes=-60))

    def test_radarr_no_match_returns_none(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["auto-unmonitored", "ignore"])
        result = fn([1, 2], id_to_label, "Test Movie")
        self.assertIsNone(result)

    def test_radarr_empty_tags_returns_none(self):
        fn = self._get_radarr_fn()
        result = fn([], {}, "Test Movie")
        self.assertIsNone(result)

    def test_radarr_multiple_matches_returns_none_and_logs(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["delayby_60", "delayby_120"])
        with self.assertLogs("radarr", level="INFO") as cm:
            result = fn([1, 2], id_to_label, "Test Movie")
        self.assertIsNone(result)
        self.assertTrue(any("Multiple delayby_" in line for line in cm.output))

    def test_radarr_case_insensitive(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["DELAYBY_90"])
        result = fn([1], id_to_label, "Test Movie")
        self.assertEqual(result, timedelta(minutes=90))

    def test_radarr_non_numeric_tag_ignored(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["delayby_abc"])
        result = fn([1], id_to_label, "Test Movie")
        self.assertIsNone(result)

    def test_radarr_zero_delay(self):
        fn = self._get_radarr_fn()
        id_to_label = self._make_id_to_label(["delayby_0"])
        result = fn([1], id_to_label, "Test Movie")
        self.assertEqual(result, timedelta(minutes=0))

    # --- sonarr (same logic, verify independently) ---

    def test_sonarr_single_match_returns_timedelta(self):
        fn = self._get_sonarr_fn()
        id_to_label = self._make_id_to_label(["delayby_30"])
        result = fn([1], id_to_label, "Test Series")
        self.assertEqual(result, timedelta(minutes=30))

    def test_sonarr_negative_value_returns_timedelta(self):
        fn = self._get_sonarr_fn()
        id_to_label = self._make_id_to_label(["delayby_-30"])
        result = fn([1], id_to_label, "Test Series")
        self.assertEqual(result, timedelta(minutes=-30))

    def test_sonarr_no_match_returns_none(self):
        fn = self._get_sonarr_fn()
        id_to_label = self._make_id_to_label(["season-pack", "auto-unmonitored"])
        result = fn([1, 2], id_to_label, "Test Series")
        self.assertIsNone(result)

    def test_sonarr_multiple_matches_returns_none_and_logs(self):
        fn = self._get_sonarr_fn()
        id_to_label = self._make_id_to_label(["delayby_60", "delayby_120"])
        with self.assertLogs("sonarr", level="INFO") as cm:
            result = fn([1, 2], id_to_label, "Test Series")
        self.assertIsNone(result)
        self.assertTrue(any("Multiple delayby_" in line for line in cm.output))


class TestRadarrDelayOverrideIntegration(unittest.TestCase):
    """Verify that radarr_app uses the per-movie delay when a delayby_ tag is present."""

    @patch("radarr.radarr_app.Config")
    @patch("radarr.radarr_app._req")
    def test_movie_with_delay_tag_uses_override(self, mock_req, mock_config):
        from datetime import datetime, timezone
        from radarr.radarr_app import _run_once

        mock_config.ENABLE_RADARR = True
        mock_config.RADARR_URL = "http://radarr"
        mock_config.RADARR_API_KEY = "key"
        mock_config.IGNORE_TAG_NAME = "ignore"
        mock_config.SKIP_IF_FILE = False
        mock_config.AUTO_TAG_NAME = "auto-unmonitored"
        mock_config.PREFERRED_RELEASE = "either"
        mock_config.IGNORE_INCINEMAS = False
        mock_config.DRY_RUN = True
        mock_config.DELAY_MINUTES = 120  # global default: 2 hours
        mock_config.RADARR_REMONITOR_WINDOW_DAYS = 0

        now = datetime.now(timezone.utc)
        # Movie released 30 minutes ago — within global 120-min delay but past the 10-min override
        release_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

        # Tag id=1 is auto-unmonitored, id=2 is delayby_10
        tags_response = MagicMock()
        tags_response.json.return_value = [
            {"id": 1, "label": "auto-unmonitored"},
            {"id": 2, "label": "delayby_10"},
        ]

        # Movie is unmonitored, has auto-tag and delayby_10 tag
        movies_response = MagicMock()
        movies_response.json.return_value = [{
            "id": 99,
            "title": "Test Movie",
            "monitored": False,
            "tags": [1, 2],  # has auto-tag and delayby_10
            "hasFile": False,
            "digitalRelease": release_time,
            "physicalRelease": None,
            "inCinemas": None,
        }]

        ensure_tag_response = MagicMock()
        ensure_tag_response.ok = True

        def req_side_effect(method, path, **kw):
            if path == "/api/v3/tag":
                return tags_response
            if path == "/api/v3/movie":
                return movies_response
            return MagicMock(ok=True, json=lambda: {})

        mock_req.side_effect = req_side_effect

        with self.assertLogs("radarr", level="INFO") as cm:
            _run_once()

        # With delayby_10 override and release 30 min ago, threshold is already past → should MONITOR
        self.assertTrue(any("MONITOR" in line for line in cm.output),
                        f"Expected MONITOR log. Got: {cm.output}")


class TestSonarrDelayOverrideIntegration(unittest.TestCase):
    """Verify that sonarr_app uses the per-series delay when a delayby_ tag is present."""

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_series_with_delay_tag_uses_override(self, mock_req, mock_config):
        from datetime import datetime, timezone
        from sonarr.sonarr_app import _run_once_inner

        mock_config.ENABLE_SONARR = True
        mock_config.SONARR_URL = "http://sonarr"
        mock_config.SONARR_API_KEY = "key"
        mock_config.IGNORE_TAG_NAME = "ignore"
        mock_config.SKIP_IF_FILE = False
        mock_config.AUTO_TAG_NAME = "auto-unmonitored"
        mock_config.DRY_RUN = True
        mock_config.DELAY_MINUTES = 120  # global default
        mock_config.SONARR_REMONITOR_WINDOW_DAYS = 0
        mock_config.SEASON_PACK_MODE = False
        mock_config.SEASON_PACK_MODE_TAG = "season-pack"

        now = datetime.now(timezone.utc)
        # Episode aired 30 minutes ago — within global 120-min delay but past the 10-min override
        air_time = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Tag id=1 is auto-unmonitored, id=2 is delayby_10
        tags_response = MagicMock()
        tags_response.json.return_value = [
            {"id": 1, "label": "auto-unmonitored"},
            {"id": 2, "label": "delayby_10"},
        ]

        # Series is monitored, has auto-tag and delayby_10 tag, one monitored season
        series_response = MagicMock()
        series_response.json.return_value = [{
            "id": 10,
            "title": "Test Series",
            "monitored": True,
            "tags": [1, 2],  # has auto-tag and delayby_10
            "seasons": [{"seasonNumber": 1, "monitored": True}],
        }]

        # Episode is unmonitored, aired 30 min ago
        episodes_response = MagicMock()
        episodes_response.json.return_value = [{
            "id": 100,
            "episodeNumber": 1,
            "title": "Pilot",
            "airDateUtc": air_time,
            "monitored": False,
            "hasFile": False,
        }]

        def req_side_effect(method, path, **kw):
            if path == "/api/v3/tag":
                return tags_response
            if path == "/api/v3/series":
                return series_response
            if path == "/api/v3/episode":
                return episodes_response
            return MagicMock(ok=True, json=lambda: {})

        mock_req.side_effect = req_side_effect

        with self.assertLogs("sonarr", level="INFO") as cm:
            _run_once_inner()

        # With delayby_10 override and episode 30 min ago, threshold is past → should MONITOR
        self.assertTrue(any("MONITOR" in line for line in cm.output),
                        f"Expected MONITOR log. Got: {cm.output}")


if __name__ == "__main__":
    unittest.main()
