"""End-to-end behaviour of a Radarr pass, run against a stateful fake API."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import radarr.radarr_app as radarr_app
from common.arr_client import ArrApiError
from tests.fakes import FakeRadarr, http_transport, make_config

AUTO = 1
IGNORE = 2
DELAY_TAG = 3

ZERO_DELAY_TAG = 4

TAGS = (
    {"id": AUTO, "label": "auto-unmonitored"},
    {"id": IGNORE, "label": "ignore"},
    {"id": DELAY_TAG, "label": "delayby_10"},
    {"id": ZERO_DELAY_TAG, "label": "delayby_0"},
)


def when(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def movie(mid=1, monitored=True, tags=(), has_file=False, digital=None, physical=None, cinemas=None):
    m = {"id": mid, "title": "Test Movie", "monitored": monitored, "tags": list(tags), "hasFile": has_file}
    if digital is not None:
        m["digitalRelease"] = when(digital)
    if physical is not None:
        m["physicalRelease"] = when(physical)
    if cinemas is not None:
        m["inCinemas"] = when(cinemas)
    return m


class RadarrRunTestCase(unittest.TestCase):
    def run_pass(self, fake, **config):
        with patch.object(radarr_app, "Config", make_config(**config)), patch.object(radarr_app, "_req", fake):
            radarr_app._run_once()
        return fake

    def state(self, fake, mid=1):
        m = fake.movies[mid]
        return m["monitored"], sorted(m["tags"])


class TestRadarrRun(RadarrRunTestCase):
    def test_future_release_is_unmonitored_and_tagged(self):
        fake = self.run_pass(FakeRadarr([movie(digital=48)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_past_threshold_with_auto_tag_is_remonitored_and_untagged(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], digital=-5)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_past_threshold_without_auto_tag_is_left_alone(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, digital=-5)], TAGS))
        self.assertEqual(self.state(fake), (False, []))
        self.assertEqual(fake.writes, [])

    def test_within_delay_stays_unmonitored(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], digital=-1)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_outside_window_is_left_alone(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], digital=-24 * 40)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_window_zero_means_unlimited(self):
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], digital=-24 * 400)], TAGS)
        self.run_pass(fake, RADARR_REMONITOR_WINDOW_DAYS=0)
        self.assertEqual(self.state(fake), (True, []))

    def test_no_release_date_is_unmonitored_and_tagged(self):
        fake = self.run_pass(FakeRadarr([movie()], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_movie_with_file_is_skipped(self):
        fake = self.run_pass(FakeRadarr([movie(has_file=True, digital=48)], TAGS))
        self.assertEqual(self.state(fake), (True, []))
        self.assertEqual(fake.writes, [])

    def test_ignored_movie_is_skipped(self):
        fake = self.run_pass(FakeRadarr([movie(tags=[IGNORE], digital=48)], TAGS))
        self.assertEqual(self.state(fake), (True, [IGNORE]))

    def test_delay_override_tag(self):
        # Released 30 min ago: inside the 2h default, past the delayby_10 override
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO, DELAY_TAG], digital=-0.5)], TAGS))
        self.assertEqual(self.state(fake), (True, [DELAY_TAG]))

    def test_either_uses_earliest_of_digital_and_physical(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], digital=48, physical=-5)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_digital_preference(self):
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], digital=48, physical=-5)], TAGS)
        self.run_pass(fake, PREFERRED_RELEASE="digital")
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_physical_preference(self):
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], digital=-5, physical=48)], TAGS)
        self.run_pass(fake, PREFERRED_RELEASE="physical")
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_cinema_only_waits_90_days(self):
        # Opened in cinemas 5 hours ago: Radarr's rule is cinema + 90 days, so not yet
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-5)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_cinema_only_still_waiting_at_89_days(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 89)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_cinema_only_remonitored_after_90_days(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 91)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_cinema_fallback_boundary(self):
        # No delay, so the threshold is exactly cinema + 90 days
        for days, expected in ((89.9, (False, [AUTO])), (90.1, (True, []))):
            fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * days)], TAGS)
            self.run_pass(fake, DELAY_MINUTES=0)
            self.assertEqual(self.state(fake), expected, days)

    def test_future_digital_date_beats_passed_cinema_fallback(self):
        # Cinema + 90 days has passed, but a digital date is now published for 2 days' time:
        # wait for the digital date, whatever the preference
        for preference in ("either", "digital", "physical"):
            fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 100, digital=48)], TAGS)
            self.run_pass(fake, PREFERRED_RELEASE=preference)
            self.assertEqual(self.state(fake), (False, [AUTO]), preference)

    def test_future_physical_date_beats_passed_cinema_fallback(self):
        for preference in ("either", "digital", "physical"):
            fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 100, physical=48)], TAGS)
            self.run_pass(fake, PREFERRED_RELEASE=preference)
            self.assertEqual(self.state(fake), (False, [AUTO]), preference)

    def test_cinema_fallback_with_physical_preference(self):
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 91)], TAGS)
        self.run_pass(fake, PREFERRED_RELEASE="physical")
        self.assertEqual(self.state(fake), (True, []))

    def test_extreme_cinema_only_date_does_not_break_the_run(self):
        odd = movie(mid=1)
        odd["inCinemas"] = "9999-12-30T00:00:00Z"
        fine = movie(mid=2, monitored=False, tags=[AUTO], digital=-5)
        fake = self.run_pass(FakeRadarr([odd, fine], TAGS))
        self.assertEqual(self.state(fake, 2), (True, []))
        self.assertEqual(self.state(fake, 1), (False, [AUTO]))  # treated as no release date

    def test_extreme_cinema_date_does_not_break_movies_with_real_dates(self):
        m = movie(monitored=False, tags=[AUTO], digital=-5)
        m["inCinemas"] = "9999-12-30T00:00:00Z"
        fake = self.run_pass(FakeRadarr([m], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_cinema_only_monitored_movie_is_unmonitored_until_day_90(self):
        # Also the upgrade case: re-monitored on its cinema date by an older version (tag
        # removed), now unmonitored and tagged again until day 90
        fake = self.run_pass(FakeRadarr([movie(cinemas=-24 * 10)], TAGS))
        self.assertEqual(self.state(fake), (False, [AUTO]))

    def test_cinema_fallback_window_counts_from_day_90(self):
        # 110 days after cinema = 20 days after the fallback date: inside the 30-day window
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 110)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_digital_date_wins_over_cinema_fallback(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 10, digital=-5)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_cinema_fallback_with_digital_preference(self):
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 91)], TAGS)
        self.run_pass(fake, PREFERRED_RELEASE="digital")
        self.assertEqual(self.state(fake), (True, []))

    def test_cinema_date_ignored_when_configured(self):
        # Past cinema + 90 days, so it would be re-monitored if the flag were ignored
        fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 91)], TAGS)
        self.run_pass(fake, IGNORE_INCINEMAS=True)
        self.assertEqual(self.state(fake), (False, [AUTO]))  # treated as no release date

    def test_ignore_incinemas_still_uses_real_dates(self):
        for preference in ("either", "digital", "physical"):
            fake = FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-24 * 10, digital=-5)], TAGS)
            self.run_pass(fake, IGNORE_INCINEMAS=True, PREFERRED_RELEASE=preference)
            self.assertEqual(self.state(fake), (True, []), preference)

    def test_dry_run_makes_no_writes(self):
        # Goes through the real _req, which is where DRY_RUN is enforced
        fake = FakeRadarr([movie(digital=48), movie(mid=2, monitored=False, tags=[AUTO], digital=-5)], TAGS)
        cfg = make_config(DRY_RUN=True)
        with patch.object(radarr_app, "Config", cfg), \
             patch("requests.Session.request", http_transport(fake, cfg.RADARR_URL, cfg.RADARR_API_KEY, self)), \
             self.assertLogs("radarr", level="INFO") as cm:
            radarr_app._run_once()
        self.assertEqual(fake.writes, [])
        self.assertGreater(len(fake.calls), 0)
        self.assertTrue(any("[DRY] PUT /api/v3/movie/editor" in l for l in cm.output))

    def test_summary_is_logged(self):
        fake = FakeRadarr([movie(digital=48), movie(mid=2, monitored=False, tags=[AUTO], digital=-5)], TAGS)
        with self.assertLogs("radarr", level="INFO") as cm:
            self.run_pass(fake)
        self.assertTrue(any("SUMMARY: Assessed 2, Managed 2, Unmonitored 1, Monitored 1" in l for l in cm.output))


    def test_zero_delay_override_is_honoured(self):
        # Regression: timedelta(0) is falsy, so delayby_0 used to fall back to the global delay
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO, ZERO_DELAY_TAG], digital=-0.5)], TAGS))
        self.assertEqual(self.state(fake), (True, [ZERO_DELAY_TAG]))

    def test_changes_are_batched_and_atomic(self):
        fake = FakeRadarr([movie(mid=1, digital=48), movie(mid=2, digital=72),
                           movie(mid=3, monitored=False, tags=[AUTO], digital=-5)], TAGS)
        self.run_pass(fake)
        self.assertEqual(fake.writes, [
            ("PUT", "/api/v3/movie/editor",
             {"movieIds": [1, 2], "monitored": False, "tags": [AUTO], "applyTags": "add"}, None),
            ("PUT", "/api/v3/movie/editor",
             {"movieIds": [3], "monitored": True, "tags": [AUTO], "applyTags": "remove"}, None),
        ])


class TestRadarrFailures(RadarrRunTestCase):
    def test_rejected_movie_is_reported_and_others_still_change(self):
        fake = FakeRadarr([movie(mid=1, digital=48), movie(mid=2, digital=48)], TAGS)
        fake.movies[2]["title"] = "Other Movie"
        fake.fail("PUT", r"/api/v3/movie/editor", 400,
                  [{"propertyName": "Path", "errorMessage": "Path is invalid"}],
                  when=lambda b: 2 in b["movieIds"])
        with self.assertLogs("radarr", level="INFO") as cm:
            self.run_pass(fake)
        self.assertEqual(self.state(fake, 1), (False, [AUTO]))
        self.assertEqual(self.state(fake, 2), (True, []))  # untouched, not half-changed
        self.assertTrue(any("ERROR" in l and "Other Movie" in l and "Path is invalid" in l for l in cm.output))
        self.assertTrue(any("SUMMARY: Assessed 2, Managed 1, Unmonitored 1, Monitored 0" in l for l in cm.output))

    def test_server_error_raises_for_retry(self):
        fake = FakeRadarr([movie(digital=48)], TAGS)
        fake.fail("PUT", r"/api/v3/movie/editor", 502)
        with self.assertRaises(ArrApiError):
            self.run_pass(fake)
        self.assertEqual(self.state(fake), (True, []))


class TestRadarrRunOnce(unittest.TestCase):
    def setUp(self):
        from common import arr_client
        arr_client._warned_unconfigured.clear()
        self.addCleanup(arr_client._warned_unconfigured.clear)

    def run_once(self, fake, **config):
        with patch.object(radarr_app, "Config", make_config(**config)), \
             patch.object(radarr_app, "_req", fake), \
             patch("common.arr_client.time.sleep") as sleep:
            radarr_app.run_once()
        return sleep

    def test_disabled_radarr_makes_no_calls(self):
        fake = FakeRadarr([])
        self.run_once(fake, ENABLE_RADARR=False)
        self.assertEqual(fake.calls, [])

    def test_enabled_without_url_warns(self):
        fake = FakeRadarr([])
        with self.assertLogs("radarr", level="WARNING") as cm:
            self.run_once(fake, RADARR_URL="")
        self.assertIn("RADARR_URL is not set", cm.output[0])

    def test_any_failure_is_logged_not_swallowed(self):
        # Previously only ReadTimeout was handled; everything else escaped to the worker
        fake = FakeRadarr([])
        fake.fail("GET", r"/api/v3/movie", 500)
        with self.assertLogs("radarr", level="WARNING") as cm:
            sleep = self.run_once(fake)
        self.assertEqual(sleep.call_count, 2)
        self.assertTrue(any("Radarr run failed after 3 attempts" in l for l in cm.output), cm.output)


if __name__ == "__main__":
    unittest.main()
