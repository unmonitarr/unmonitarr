"""End-to-end behaviour of a Sonarr pass, run against a stateful fake API.

These pin down what a run actually does to series and episodes, so the module can be
refactored safely. Assertions are on the fake's end state, not on call sequences.
"""
import unittest
from unittest.mock import patch

import sonarr.sonarr_app as sonarr_app
from tests.fakes import FakeSonarr, hours_from_now, http_transport, make_config

AUTO = 1
IGNORE = 2
SEASON_PACK = 3
DELAY_TAG = 4

TAGS = (
    {"id": AUTO, "label": "auto-unmonitored"},
    {"id": IGNORE, "label": "ignore"},
    {"id": SEASON_PACK, "label": "season-pack"},
    {"id": DELAY_TAG, "label": "delayby_10"},
)


def series(sid=10, tags=(), monitored=True, seasons=((1, True),), title="Test Series"):
    return {
        "id": sid,
        "title": title,
        "monitored": monitored,
        "tags": list(tags),
        "seasons": [{"seasonNumber": n, "monitored": m} for n, m in seasons],
    }


def episode(eid, number=1, air_hours=None, monitored=True, has_file=False, title="Episode"):
    """air_hours: offset from now in hours (negative = already aired). None = no air date."""
    e = {"id": eid, "episodeNumber": number, "title": title, "monitored": monitored, "hasFile": has_file}
    if air_hours is not None:
        e["airDateUtc"] = hours_from_now(air_hours)
    return e


class SonarrRunTestCase(unittest.TestCase):
    def run_pass(self, fake, **config):
        cfg = make_config(**config)
        with patch.object(sonarr_app, "Config", cfg), patch.object(sonarr_app, "_req", fake):
            sonarr_app._run_once_inner()
        return fake

    def monitored(self, fake, eid):
        return fake.episode(eid)["monitored"]

    def series_tags(self, fake, sid=10):
        return fake.series[sid]["tags"]


class TestStandardMode(SonarrRunTestCase):
    def test_future_episode_is_unmonitored_and_series_tagged(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_aired_but_within_delay_is_unmonitored(self):
        # Aired 1h ago, default delay is 2h, so the threshold hasn't passed
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=-1)]}, TAGS)
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_existing_series_tags_are_preserved_when_tagging(self):
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        self.run_pass(fake)
        self.assertEqual(sorted(self.series_tags(fake)), sorted([SEASON_PACK, AUTO]))

    def test_aired_past_delay_with_auto_tag_is_remonitored(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))

    def test_aired_past_delay_without_auto_tag_is_left_alone(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertEqual(fake.writes, [])

    def test_aired_outside_remonitor_window_is_left_alone(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-24 * 20, monitored=False)]}, TAGS)
        self.run_pass(fake, SONARR_REMONITOR_WINDOW_DAYS=14)
        self.assertFalse(self.monitored(fake, 100))

    def test_window_zero_means_unlimited(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-24 * 400, monitored=False)]}, TAGS)
        self.run_pass(fake, SONARR_REMONITOR_WINDOW_DAYS=0)
        self.assertTrue(self.monitored(fake, 100))

    def test_episode_with_file_is_skipped(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48, has_file=True)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertEqual(fake.writes, [])

    def test_episode_with_file_is_managed_when_skip_if_file_off(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48, has_file=True)]}, TAGS)
        self.run_pass(fake, SKIP_IF_FILE=False)
        self.assertFalse(self.monitored(fake, 100))

    def test_monitored_episode_without_air_date_is_unmonitored(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=None)]}, TAGS)
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_ignored_series_is_not_touched(self):
        fake = FakeSonarr([series(tags=[IGNORE])], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertEqual(fake.writes, [])

    def test_unmonitored_series_is_not_touched(self):
        fake = FakeSonarr([series(monitored=False)], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))

    def test_unmonitored_season_is_not_touched(self):
        fake = FakeSonarr(
            [series(seasons=((1, False), (2, True)))],
            {(10, 1): [episode(100, air_hours=48)], (10, 2): [episode(200, air_hours=48)]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 200))

    def test_all_monitored_seasons_are_processed(self):
        fake = FakeSonarr(
            [series(seasons=((1, True), (2, True)))],
            {(10, 1): [episode(100, air_hours=48)], (10, 2): [episode(200, air_hours=72)]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 200))

    def test_delay_override_tag_applies_to_series(self):
        # Aired 30 min ago: inside the 2h default, but past the delayby_10 override
        fake = FakeSonarr(
            [series(tags=[AUTO, DELAY_TAG])],
            {(10, 1): [episode(100, air_hours=-0.5, monitored=False)]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))

    def test_negative_delay_remonitors_before_air(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=0.5, monitored=False)]}, TAGS)
        self.run_pass(fake, DELAY_MINUTES=-60)
        self.assertTrue(self.monitored(fake, 100))

    def test_auto_tag_is_created_when_missing(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48)]}, tags=())
        self.run_pass(fake)
        new_id = fake.tag_id("auto-unmonitored")
        self.assertIsNotNone(new_id)
        self.assertIn(new_id, self.series_tags(fake))

    def test_dry_run_makes_no_writes(self):
        fake = FakeSonarr(
            [series(tags=[AUTO])],
            {(10, 1): [episode(100, air_hours=48), episode(101, number=2, air_hours=-5, monitored=False)]},
            TAGS,
        )
        cfg = make_config(DRY_RUN=True, SONARR_REFRESH_TBA=True)
        fake.episode(101)["title"] = "TBA"
        with patch.object(sonarr_app, "Config", cfg), \
             patch("requests.Session.request", http_transport(fake, cfg.SONARR_URL, cfg.SONARR_API_KEY, self)), \
             self.assertLogs("sonarr", level="INFO") as cm:
            sonarr_app._run_once_inner()
        self.assertEqual(fake.writes, [])
        self.assertTrue(any("[DRY] PUT /api/v3/episode/monitor" in l for l in cm.output))
        self.assertTrue(any("[DRY] POST /api/v3/command" in l for l in cm.output))
        self.assertTrue(any("UNMONITOR" in line for line in cm.output))
        self.assertTrue(any("MONITOR:" in line for line in cm.output))

    def test_summary_is_logged(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        with self.assertLogs("sonarr", level="INFO") as cm:
            self.run_pass(fake)
        self.assertTrue(any("SUMMARY: Assessed 1, Managed 1, Unmonitored 1, Monitored 0" in l for l in cm.output))


class TestAutoTagRemoval(SonarrRunTestCase):
    def test_tag_kept_while_future_episodes_pending(self):
        fake = FakeSonarr(
            [series(tags=[AUTO])],
            {(10, 1): [
                episode(100, number=1, air_hours=-5, monitored=False),
                episode(101, number=2, air_hours=24 * 7, monitored=False),
            ]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_tag_after_last_pending_episode_remonitored(self):
        # KNOWN BUG (fixed in bug/silent-failures): the removal check reads episode state from
        # before this run's update, so the episode just re-monitored still counts as pending and
        # the tag is never removed. This test pins current behaviour; flip it with the fix.
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))


class TestSeasonPackMode(SonarrRunTestCase):
    def season(self, ep1_hours, ep2_hours, ep3_monitored=False):
        return [
            episode(100, number=1, air_hours=ep1_hours, monitored=False),
            episode(101, number=2, air_hours=ep2_hours, monitored=False),
            episode(102, number=3, air_hours=None, monitored=ep3_monitored),
        ]

    def test_trigger_met_remonitors_whole_season(self):
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): self.season(-5, 24 * 7)}, TAGS)
        with self.assertLogs("sonarr", level="INFO") as cm:
            self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(self.monitored(fake, 100))
        self.assertTrue(self.monitored(fake, 101))  # future episode, re-monitored with the season
        self.assertFalse(self.monitored(fake, 102))  # no air date, skipped
        self.assertTrue(any("SEASON PACK MODE: Re-monitored 2 episodes" in l for l in cm.output))

    def test_trigger_met_skips_episodes_with_files(self):
        eps = self.season(-5, 24 * 7)
        eps[1]["hasFile"] = True
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))

    def test_trigger_met_without_auto_tag_does_nothing(self):
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): self.season(-5, 24 * 7)}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertFalse(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))

    def test_trigger_not_met_unmonitors_monitored_episodes(self):
        eps = [
            episode(100, number=1, air_hours=48, monitored=True),
            episode(101, number=2, air_hours=24 * 9, monitored=True),
            episode(102, number=3, air_hours=None, monitored=True),
        ]
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        for eid in (100, 101, 102):
            self.assertFalse(self.monitored(fake, eid), eid)
        self.assertIn(AUTO, self.series_tags(fake))

    def test_trigger_is_lowest_numbered_episode_with_air_date(self):
        eps = [
            episode(100, number=1, air_hours=None, monitored=False),
            episode(101, number=2, air_hours=-5, monitored=False),
            episode(102, number=3, air_hours=24 * 7, monitored=False),
        ]
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(self.monitored(fake, 101))
        self.assertTrue(self.monitored(fake, 102))

    def test_season_pack_tag_ignored_when_mode_disabled(self):
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): self.season(-5, 24 * 7)}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=False)
        self.assertTrue(self.monitored(fake, 100))   # aired, standard re-monitor
        self.assertFalse(self.monitored(fake, 101))  # future, standard mode leaves it


class TestRunOnceGating(unittest.TestCase):
    def test_disabled_sonarr_makes_no_calls(self):
        fake = FakeSonarr([], {})
        with patch.object(sonarr_app, "Config", make_config(ENABLE_SONARR=False)), \
             patch.object(sonarr_app, "_req", fake):
            sonarr_app.run_once()
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
