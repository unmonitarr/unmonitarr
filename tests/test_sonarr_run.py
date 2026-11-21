"""End-to-end behaviour of a Sonarr pass, run against a stateful fake API.

These pin down what a run actually does to series and episodes, so the module can be
refactored safely. Assertions are on the fake's end state, not on call sequences.
"""
import unittest
from unittest.mock import patch

from common.arr_client import ArrApiError

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
        self.assertEqual([c[1] for c in fake.calls],
                         ["/api/v3/tag", "/api/v3/series", "/api/v3/episode"])
        dry = [l.split("INFO:sonarr:", 1)[1] for l in cm.output if "[DRY]" in l]
        self.assertEqual(dry, [
            '[DRY] PUT /api/v3/episode/monitor -> {"episodeIds": [100], "monitored": false}',
            '[DRY] PUT /api/v3/episode/monitor -> {"episodeIds": [101], "monitored": true}',
            '[DRY] POST /api/v3/command -> {"name": "RefreshSeries", "seriesId": 10}',
        ])  # no tag removal: episode 100 was just unmonitored and is still pending
        self.assertTrue(any("UNMONITOR" in line for line in cm.output))
        self.assertTrue(any("MONITOR:" in line for line in cm.output))

    def test_summary_is_logged(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48)]}, TAGS)
        with self.assertLogs("sonarr", level="INFO") as cm:
            self.run_pass(fake)
        self.assertTrue(any("SUMMARY: Assessed 1, Managed 1, Unmonitored 1, Monitored 0" in l for l in cm.output))


class TestEdgeCases(SonarrRunTestCase):
    """Pins behaviour that is easy to change by accident."""

    def test_ignore_tag_matches_case_insensitively(self):
        tags = TAGS[:1] + ({"id": IGNORE, "label": "Ignore"},)
        fake = FakeSonarr([series(tags=[IGNORE])], {(10, 1): [episode(100, air_hours=48)]}, tags)
        self.run_pass(fake, IGNORE_TAG_NAME="ignore")
        self.assertTrue(self.monitored(fake, 100))

    def test_no_air_date_with_file_is_left_alone(self):
        # Regression: this used to be unmonitored, tagged and untagged in the same pass,
        # leaving it unmonitored for good
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=None, has_file=True)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertEqual(fake.writes, [])

    def test_season_pack_before_trigger_leaves_episodes_with_files(self):
        eps = [episode(100, number=1, air_hours=10, monitored=True, has_file=True),
               episode(101, number=2, air_hours=24 * 7, monitored=True)]
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_no_tag_churn_when_only_files_present(self):
        eps = [episode(100, number=1, air_hours=10, monitored=True, has_file=True)]
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertEqual(fake.writes, [])

    def test_season_pack_respects_remonitor_window(self):
        eps = [episode(100, number=1, air_hours=-24 * 20, monitored=False),
               episode(101, number=2, air_hours=48, monitored=False)]
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True, SONARR_REMONITOR_WINDOW_DAYS=14)
        self.assertFalse(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))

    def test_season_pack_before_trigger_uses_trigger_threshold(self):
        # Episode 2 aired 5h ago but episode 1 (the trigger) is still 2 days away, so the
        # whole season waits on the trigger
        eps = [episode(100, number=1, air_hours=48, monitored=True),
               episode(101, number=2, air_hours=-5, monitored=True)]
        fake = FakeSonarr([series(tags=[SEASON_PACK])], {(10, 1): eps}, TAGS)
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertFalse(self.monitored(fake, 101))

    def test_season_pack_summary_counts(self):
        eps = [episode(100, number=1, air_hours=-5, monitored=False),
               episode(101, number=2, air_hours=48, monitored=False),
               episode(102, number=3, air_hours=None, monitored=False)]
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): eps}, TAGS)
        with self.assertLogs("sonarr", level="INFO") as cm:
            self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(any("SUMMARY: Assessed 3, Managed 2, Unmonitored 0, Monitored 2" in l for l in cm.output),
                        cm.output)


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

    def test_tag_removed_after_last_pending_episode_remonitored(self):
        # Regression: the check used to read pre-update state, so the episode just
        # re-monitored counted as pending and the tag was never removed
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertNotIn(AUTO, self.series_tags(fake))

    def test_tag_kept_when_episode_unmonitored_in_same_pass(self):
        # One episode re-monitored, another unmonitored in the same pass. The second reads
        # as monitored in pre-update state; removing the tag would strand it.
        fake = FakeSonarr(
            [series(tags=[AUTO])],
            {(10, 1): [
                episode(100, number=1, air_hours=-5, monitored=False),
                episode(101, number=2, air_hours=48, monitored=True),
            ]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))
        self.assertIn(AUTO, self.series_tags(fake))

    def test_tag_kept_for_unmonitored_episode_without_air_date(self):
        fake = FakeSonarr(
            [series(tags=[AUTO])],
            {(10, 1): [
                episode(100, number=1, air_hours=-5, monitored=False),
                episode(101, number=2, air_hours=None, monitored=False),
            ]},
            TAGS,
        )
        self.run_pass(fake)
        self.assertIn(AUTO, self.series_tags(fake))

    def test_stale_tag_cleaned_up_without_any_remonitor(self):
        # A tag left behind by older versions: nothing pending, nothing re-monitored this pass
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-24 * 30, monitored=True)]}, TAGS)
        self.run_pass(fake)
        self.assertNotIn(AUTO, self.series_tags(fake))

    def test_tag_on_untracked_series_is_left_alone(self):
        fake = FakeSonarr([series(tags=[AUTO], monitored=False)], {(10, 1): [episode(100, air_hours=-24 * 30)]}, TAGS)
        self.run_pass(fake)
        self.assertIn(AUTO, self.series_tags(fake))

    def test_season_pack_remonitor_removes_tag(self):
        fake = FakeSonarr(
            [series(tags=[AUTO, SEASON_PACK])],
            {(10, 1): [episode(100, number=1, air_hours=-5, monitored=False),
                       episode(101, number=2, air_hours=48, monitored=False)]},
            TAGS,
        )
        self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(self.monitored(fake, 101))
        self.assertNotIn(AUTO, self.series_tags(fake))
        self.assertIn(SEASON_PACK, self.series_tags(fake))


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


class TestFailures(SonarrRunTestCase):
    """A failed write must never pass silently or strand an episode without the auto-tag."""

    VALIDATION = [{"propertyName": "RootFolderPath", "errorMessage": "Root folder does not exist"}]

    def two_series(self):
        return FakeSonarr(
            [series(sid=10, title="Test Series"), series(sid=20, title="Other Series")],
            {(10, 1): [episode(100, air_hours=48)], (20, 1): [episode(200, air_hours=48)]},
            TAGS,
        )

    def test_series_rejected_by_editor_keeps_its_episodes_monitored(self):
        fake = self.two_series()
        fake.fail("PUT", r"/api/v3/series/editor", 400, self.VALIDATION, when=lambda b: 20 in b["seriesIds"])
        with self.assertLogs("sonarr", level="ERROR") as cm:
            self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake, 10))
        self.assertTrue(self.monitored(fake, 200))
        self.assertNotIn(AUTO, self.series_tags(fake, 20))
        self.assertTrue(any("Other Series" in l and "Root folder does not exist" in l for l in cm.output), cm.output)

    def test_episode_write_failure_raises_after_tagging(self):
        fake = self.two_series()
        fake.fail("PUT", r"/api/v3/episode/monitor", 500)
        with self.assertRaises(ArrApiError):
            self.run_pass(fake)
        # Tagged first, so a later pass can still re-monitor once the unmonitor succeeds
        self.assertIn(AUTO, self.series_tags(fake, 10))
        self.assertTrue(self.monitored(fake, 100))

    def test_tag_removal_failure_is_a_warning_and_remonitor_stands(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        fake.fail("PUT", r"/api/v3/series/editor", 400, self.VALIDATION)
        with self.assertLogs("sonarr", level="WARNING") as cm:
            self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertIn(AUTO, self.series_tags(fake))
        self.assertTrue(any("will retry next run" in l for l in cm.output), cm.output)

    def test_unreadable_air_date_is_logged_and_skipped(self):
        eps = [episode(100, number=1, air_hours=48), episode(101, number=2, air_hours=48)]
        eps[0]["airDateUtc"] = "not-a-date"
        fake = FakeSonarr([series()], {(10, 1): eps}, TAGS)
        with self.assertLogs("sonarr", level="WARNING") as cm:
            self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertFalse(self.monitored(fake, 101))
        self.assertTrue(any("unreadable air date" in l for l in cm.output), cm.output)

    def test_fractional_seconds_air_date_is_understood(self):
        e = episode(100, air_hours=48)
        e["airDateUtc"] = e["airDateUtc"].replace("Z", ".000Z")
        fake = FakeSonarr([series()], {(10, 1): [e]}, TAGS)
        self.run_pass(fake)
        self.assertFalse(self.monitored(fake, 100))

    def test_season_pack_unreadable_trigger_date_is_logged(self):
        eps = [episode(100, number=1, air_hours=-5, monitored=False)]
        eps[0]["airDateUtc"] = "garbage"
        fake = FakeSonarr([series(tags=[AUTO, SEASON_PACK])], {(10, 1): eps}, TAGS)
        with self.assertLogs("sonarr", level="WARNING") as cm:
            self.run_pass(fake, SEASON_PACK_MODE=True)
        self.assertTrue(any("unreadable air date" in l for l in cm.output), cm.output)

    def test_episode_write_failure_names_the_series(self):
        fake = self.two_series()
        fake.fail("PUT", r"/api/v3/episode/monitor", 400, {"message": "Bad"})
        with self.assertRaises(ArrApiError) as cm:
            self.run_pass(fake)
        self.assertIn("Couldn't unmonitor 2 episode(s) in Other Series, Test Series", str(cm.exception))
        self.assertIn("Bad", str(cm.exception))

    def test_transient_failure_removing_tag_is_a_warning(self):
        fake = FakeSonarr([series(tags=[AUTO])], {(10, 1): [episode(100, air_hours=-5, monitored=False)]}, TAGS)
        fake.fail("PUT", r"/api/v3/series/editor", 503)
        with self.assertLogs("sonarr", level="WARNING") as cm:
            self.run_pass(fake)
        self.assertTrue(self.monitored(fake, 100))
        self.assertTrue(any("will retry next run" in l for l in cm.output), cm.output)

    def test_transient_failure_during_per_series_fallback_raises(self):
        # Batch rejected (400) -> retried per series -> one gets a 503: retry the whole pass,
        # and nothing is unmonitored yet
        fake = self.two_series()
        fake.fail("PUT", r"/api/v3/series/editor", 400, self.VALIDATION, when=lambda b: len(b["seriesIds"]) > 1)
        fake.fail("PUT", r"/api/v3/series/editor", 503, when=lambda b: b["seriesIds"] == [20])
        with self.assertRaises(ArrApiError) as cm:
            self.run_pass(fake)
        self.assertTrue(cm.exception.transient)
        self.assertTrue(self.monitored(fake, 100))
        self.assertTrue(self.monitored(fake, 200))

    def test_rejected_tag_name_reports_server_message(self):
        fake = FakeSonarr([series()], {(10, 1): [episode(100, air_hours=48)]}, tags=())
        fake.fail("POST", r"/api/v3/tag", 400, [{"propertyName": "Label",
                                                 "errorMessage": "Allowed characters a-z, 0-9 and -"}])
        with self.assertRaises(ArrApiError) as cm:
            self.run_pass(fake, AUTO_TAG_NAME="auto_unmonitored")
        self.assertIn("auto_unmonitored", str(cm.exception))
        self.assertIn("Allowed characters", str(cm.exception))


class TestRunOnce(unittest.TestCase):
    def setUp(self):
        from common import arr_client
        arr_client._warned_unconfigured.clear()

    def run_once(self, fake, **config):
        with patch.object(sonarr_app, "Config", make_config(**config)), \
             patch.object(sonarr_app, "_req", fake), \
             patch("common.arr_client.time.sleep") as sleep:
            sonarr_app.run_once()
        return sleep

    def test_disabled_sonarr_makes_no_calls(self):
        fake = FakeSonarr([], {})
        self.run_once(fake, ENABLE_SONARR=False)
        self.assertEqual(fake.calls, [])

    def test_enabled_without_api_key_warns(self):
        fake = FakeSonarr([], {})
        with self.assertLogs("sonarr", level="WARNING") as cm:
            self.run_once(fake, SONARR_API_KEY="")
        self.assertEqual(fake.calls, [])
        self.assertIn("SONARR_API_KEY is not set", cm.output[0])

    def test_unconfigured_warning_is_logged_once(self):
        fake = FakeSonarr([], {})
        with self.assertLogs("sonarr", level="DEBUG") as cm:
            self.run_once(fake, SONARR_API_KEY="")
            self.run_once(fake, SONARR_API_KEY="")
        self.assertEqual(sum("WARNING" in l for l in cm.output), 1)

    def test_bad_api_key_is_one_clear_error_without_retries(self):
        fake = FakeSonarr([], {})
        fake.fail("GET", r"/api/v3/tag", 401, {"message": "Unauthorized"})
        with self.assertLogs("sonarr", level="ERROR") as cm:
            sleep = self.run_once(fake)
        sleep.assert_not_called()
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(any("401" in l and "check the API key" in l for l in cm.output), cm.output)

    def test_server_error_is_retried(self):
        fake = FakeSonarr([], {})
        fake.fail("GET", r"/api/v3/tag", 503)
        with self.assertLogs("sonarr", level="WARNING") as cm:
            sleep = self.run_once(fake)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(len(fake.calls), 3)
        self.assertTrue(any("after 3 attempts" in l for l in cm.output), cm.output)


if __name__ == "__main__":
    unittest.main()
