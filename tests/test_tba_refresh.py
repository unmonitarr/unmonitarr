import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


class TestIsTbaTitle(unittest.TestCase):
    """Tests for _is_tba_title in sonarr_app."""

    def _fn(self):
        from sonarr.sonarr_app import _is_tba_title
        return _is_tba_title

    def test_matches_tba_variants(self):
        fn = self._fn()
        for title in ("TBA", "tba", "  TBA  ", "TBD", "tbd", "Tba"):
            self.assertTrue(fn(title), f"Expected {title!r} to be treated as TBA")

    def test_matches_missing_titles(self):
        fn = self._fn()
        for title in ("", "   ", None):
            self.assertTrue(fn(title), f"Expected {title!r} to be treated as TBA")

    def test_does_not_match_real_titles(self):
        fn = self._fn()
        for title in ("TBA or Not", "A Real Episode Title", "Pilot", "TBAlicious"):
            self.assertFalse(fn(title), f"Expected {title!r} to be treated as a real title")


class TestTbaRefreshIntegration(unittest.TestCase):
    """Verify _run_once_inner fires RefreshSeries for monitored TBA episodes."""

    def setUp(self):
        # _tba_refresh_last is module-level state, so clear it between tests
        import sonarr.sonarr_app as sonarr_app
        sonarr_app._tba_refresh_last.clear()
        self.now = datetime.now(timezone.utc)

    def _air(self, **delta):
        return (self.now - timedelta(**delta)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _configure(self, mock_config, refresh_tba=True):
        """Every attribute the code reads must be set explicitly - an unset attribute
        on a MagicMock is truthy and would silently flip a branch."""
        mock_config.ENABLE_SONARR = True
        mock_config.SONARR_URL = "http://sonarr"
        mock_config.SONARR_API_KEY = "key"
        mock_config.IGNORE_TAG_NAME = "ignore"
        mock_config.SKIP_IF_FILE = True
        mock_config.AUTO_TAG_NAME = "auto-unmonitored"
        mock_config.DRY_RUN = True
        mock_config.DELAY_MINUTES = 120
        mock_config.SONARR_REMONITOR_WINDOW_DAYS = 0
        mock_config.SEASON_PACK_MODE = False
        mock_config.SEASON_PACK_MODE_TAG = "season-pack"
        mock_config.SONARR_REFRESH_TBA = refresh_tba

    def _wire(self, mock_req, episodes, series_tags=(1,)):
        """Route _req by path. Series 10 is monitored with one monitored season."""
        tags_response = MagicMock()
        tags_response.json.return_value = [
            {"id": 1, "label": "auto-unmonitored"},
            {"id": 2, "label": "ignore"},
        ]

        series_response = MagicMock()
        series_response.json.return_value = [{
            "id": 10,
            "title": "Test Series",
            "monitored": True,
            "tags": list(series_tags),
            "seasons": [{"seasonNumber": 2, "monitored": True}],
        }]

        episodes_response = MagicMock()
        episodes_response.json.return_value = episodes

        def side_effect(method, path, **kw):
            if path == "/api/v3/tag":
                return tags_response
            if path == "/api/v3/series":
                return series_response
            if path == "/api/v3/episode":
                return episodes_response
            return MagicMock(ok=True, json=lambda: {})

        mock_req.side_effect = side_effect

    def _episode(self, **overrides):
        episode = {
            "id": 100,
            "episodeNumber": 5,
            "title": "TBA",
            "airDateUtc": self._air(hours=2),
            "monitored": True,
            "hasFile": False,
        }
        episode.update(overrides)
        return episode

    def _refresh_calls(self, mock_req):
        return [c for c in mock_req.call_args_list if c[0][1] == "/api/v3/command"]

    def _run(self, mock_req, mock_config, episodes, refresh_tba=True, series_tags=(1,)):
        from sonarr.sonarr_app import _run_once_inner
        self._configure(mock_config, refresh_tba=refresh_tba)
        self._wire(mock_req, episodes, series_tags=series_tags)
        with self.assertLogs("sonarr", level="DEBUG") as cm:
            _run_once_inner()
        return cm.output

    # --- fires ---

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_monitored_tba_episode_triggers_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config, [self._episode()])
        self.assertTrue(any("TBA REFRESH: Test Series" in line for line in output),
                        f"Expected TBA REFRESH log. Got: {output}")
        self.assertTrue(any('"name": "RefreshSeries"' in line and '"seriesId": 10' in line
                            for line in output),
                        f"Expected RefreshSeries payload in dry-run log. Got: {output}")

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_tbd_title_triggers_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config, [self._episode(title="TBD")])
        self.assertTrue(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_empty_title_triggers_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config, [self._episode(title="")])
        self.assertTrue(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_missing_title_triggers_refresh(self, mock_req, mock_config):
        episode = self._episode()
        del episode["title"]
        output = self._run(mock_req, mock_config, [episode])
        self.assertTrue(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_episode_with_file_still_triggers_refresh(self, mock_req, mock_config):
        # SKIP_IF_FILE excludes it from monitoring changes, but the title still matters
        output = self._run(mock_req, mock_config, [self._episode(hasFile=True)])
        self.assertTrue(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_episode_remonitored_this_run_triggers_refresh(self, mock_req, mock_config):
        # The cached episode dict reads monitored=False, but we re-monitor it this run.
        # This is the core case: refresh at the moment the episode becomes relevant.
        output = self._run(mock_req, mock_config, [self._episode(monitored=False)])
        self.assertTrue(any("MONITOR:" in line for line in output),
                        f"Expected the episode to be re-monitored. Got: {output}")
        self.assertTrue(any("TBA REFRESH" in line for line in output), output)

    # --- does not fire ---

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_real_title_does_not_trigger_refresh(self, mock_req, mock_config):
        self._run(mock_req, mock_config,
                  [self._episode(title="A Real Episode Title")])
        self.assertEqual(self._refresh_calls(mock_req), [])

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_feature_disabled_does_not_trigger_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config, [self._episode()], refresh_tba=False)
        self.assertFalse(any("TBA REFRESH" in line for line in output), output)
        self.assertEqual(self._refresh_calls(mock_req), [])

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_outside_window_does_not_trigger_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config,
                           [self._episode(airDateUtc=self._air(hours=100))])
        self.assertFalse(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_unaired_episode_does_not_trigger_refresh(self, mock_req, mock_config):
        future = (self.now + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
        output = self._run(mock_req, mock_config, [self._episode(airDateUtc=future)])
        self.assertFalse(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_no_air_date_does_not_trigger_refresh(self, mock_req, mock_config):
        output = self._run(mock_req, mock_config, [self._episode(airDateUtc=None)])
        self.assertFalse(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_unmonitored_episode_does_not_trigger_refresh(self, mock_req, mock_config):
        # Series has no auto-tag, so the aired TBA episode is left unmonitored. We only
        # care about episodes Sonarr is actually going to grab.
        output = self._run(mock_req, mock_config, [self._episode(monitored=False)],
                           series_tags=())
        self.assertFalse(any("MONITOR:" in line for line in output),
                         f"Episode should not be re-monitored without the auto-tag. Got: {output}")
        self.assertFalse(any("TBA REFRESH" in line for line in output), output)

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_cooldown_suppresses_second_refresh(self, mock_req, mock_config):
        from sonarr.sonarr_app import _run_once_inner
        self._configure(mock_config)
        self._wire(mock_req, [self._episode()])

        with self.assertLogs("sonarr", level="DEBUG") as first:
            _run_once_inner()
        self.assertTrue(any("TBA REFRESH" in line for line in first.output), first.output)

        with self.assertLogs("sonarr", level="DEBUG") as second:
            _run_once_inner()
        self.assertFalse(any("TBA REFRESH:" in line for line in second.output),
                         f"Cooldown should suppress the second refresh. Got: {second.output}")
        self.assertTrue(any("on cooldown" in line for line in second.output), second.output)

    @patch("sonarr.sonarr_app._TBA_COOLDOWN", timedelta(seconds=0))
    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_refresh_repeats_once_cooldown_expires(self, mock_req, mock_config):
        from sonarr.sonarr_app import _run_once_inner
        self._configure(mock_config)
        self._wire(mock_req, [self._episode()])

        for attempt in (1, 2):
            with self.assertLogs("sonarr", level="DEBUG") as cm:
                _run_once_inner()
            self.assertTrue(any("TBA REFRESH" in line for line in cm.output),
                            f"Run {attempt} should refresh. Got: {cm.output}")

    # --- live (non dry-run) call shape ---

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_live_run_posts_refresh_command(self, mock_req, mock_config):
        from sonarr.sonarr_app import _run_once_inner
        self._configure(mock_config)
        mock_config.DRY_RUN = False
        self._wire(mock_req, [self._episode()])

        with self.assertLogs("sonarr", level="DEBUG"):
            _run_once_inner()

        mock_req.assert_any_call(
            "POST", "/api/v3/command",
            json={"name": "RefreshSeries", "seriesId": 10},
        )

    @patch("sonarr.sonarr_app.Config")
    @patch("sonarr.sonarr_app._req")
    def test_failed_refresh_does_not_abort_run(self, mock_req, mock_config):
        from sonarr.sonarr_app import _run_once_inner
        self._configure(mock_config)
        mock_config.DRY_RUN = False
        self._wire(mock_req, [self._episode()])

        original = mock_req.side_effect

        def failing(method, path, **kw):
            if path == "/api/v3/command":
                raise RuntimeError("sonarr exploded")
            return original(method, path, **kw)

        mock_req.side_effect = failing

        with self.assertLogs("sonarr", level="DEBUG") as cm:
            _run_once_inner()  # must not raise

        self.assertTrue(any("TBA refresh failed" in line for line in cm.output), cm.output)
        self.assertTrue(any("SUMMARY:" in line for line in cm.output),
                        f"Run should complete past the refresh pass. Got: {cm.output}")


if __name__ == "__main__":
    unittest.main()
