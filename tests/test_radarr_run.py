"""End-to-end behaviour of a Radarr pass, run against a stateful fake API."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import radarr.radarr_app as radarr_app
from tests.fakes import FakeRadarr, http_transport, make_config

AUTO = 1
IGNORE = 2
DELAY_TAG = 3

TAGS = (
    {"id": AUTO, "label": "auto-unmonitored"},
    {"id": IGNORE, "label": "ignore"},
    {"id": DELAY_TAG, "label": "delayby_10"},
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

    def test_cinema_date_used_only_as_fallback(self):
        fake = self.run_pass(FakeRadarr([movie(monitored=False, tags=[AUTO], cinemas=-5)], TAGS))
        self.assertEqual(self.state(fake), (True, []))

    def test_cinema_date_ignored_when_configured(self):
        fake = FakeRadarr([movie(cinemas=-5)], TAGS)
        self.run_pass(fake, IGNORE_INCINEMAS=True)
        self.assertEqual(self.state(fake), (False, [AUTO]))  # treated as no release date

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


class TestRadarrRunOnceGating(unittest.TestCase):
    def test_disabled_radarr_makes_no_calls(self):
        fake = FakeRadarr([])
        with patch.object(radarr_app, "Config", make_config(ENABLE_RADARR=False)), \
             patch.object(radarr_app, "_req", fake):
            radarr_app.run_once()
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
