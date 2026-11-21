from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from common import arr_client
from common.logger import get_logger
from core.config import Config

log = get_logger("sonarr")
AIR_FMT = "%Y-%m-%dT%H:%M:%SZ"

# Placeholder episode titles that indicate metadata hasn't landed yet
_TBA_TITLES = {"tba", "tbd"}

# Only refresh episodes that aired recently. Sonarr's own "Episode Title Required"
# grace period is 48h, after which it imports as TBA regardless, so there is little
# value in refreshing beyond that. Bounded so episodes that never get a real title
# (specials, some anime) don't get refreshed indefinitely.
_TBA_WINDOW = timedelta(hours=72)

# Decouples refresh frequency from trigger frequency (SLEEP_MINUTES plus webhooks).
_TBA_COOLDOWN = timedelta(minutes=60)

# series_id -> datetime of last RefreshSeries. In-memory only; a restart just means
# one extra refresh per affected series.
_tba_refresh_last = {}


# --- API helpers -----------------------------------------------------------------

def _req(method: str, path: str, **kw):
    return arr_client.request(Config.SONARR_URL, Config.SONARR_API_KEY, method, path,
                              dry_run=Config.DRY_RUN, log=log, **kw)


def _tags_map():
    return arr_client.fetch_tags(_req)


def _ensure_tag(label, label_to_id):
    return arr_client.ensure_tag(_req, label, label_to_id, dry_run=Config.DRY_RUN, log=log)


def _get_delay_override(tag_ids, id_to_label, title="unknown"):
    """Return a timedelta override if a delayby_<N> tag is found, else None."""
    return arr_client.get_delay_override(tag_ids, id_to_label, title, log)


def _get(path, **kw):
    return arr_client.get_json(_req, path, **kw)


def _edit_series_tags(series_ids, tag_id, mode):
    """Add or remove a tag on several series in one call. Returns {series_id: error} for failures."""
    return arr_client.bulk_edit(_req, "/api/v3/series/editor", "seriesIds", series_ids,
                                {"tags": [tag_id], "applyTags": mode})


def _air_date(p, sid, season, e):
    """An episode's air date, or None. Logs a warning if the date is present but unreadable."""
    air = e.get("airDateUtc")
    if not air:
        return None
    air_dt = arr_client.parse_iso(air)
    if air_dt is None:
        log.warning("Skipping episode with unreadable air date %r: %s", air, p.describe(sid, season, e))
    return air_dt


def _is_tba_title(title) -> bool:
    """True if an episode title is missing, blank, or a TBA/TBD placeholder."""
    t = (title or "").strip()
    return not t or t.lower() in _TBA_TITLES


# --- One pass --------------------------------------------------------------------

@dataclass
class _Pass:
    """State for one run: inputs that don't change, and the decisions made so far."""
    now: datetime
    auto_tag_id: int
    remonitor_window: Optional[timedelta]  # None = unlimited
    series_map: dict
    series_with_auto_tag: set
    eps_to_monitor: list = field(default_factory=list)
    eps_to_unmonitor: list = field(default_factory=list)
    episode_series: dict = field(default_factory=dict)  # episode id -> series id, for every decision
    series_to_tag: set = field(default_factory=set)
    assessed: int = 0
    _monitor_set: set = field(default_factory=set, repr=False)
    _unmonitor_set: set = field(default_factory=set, repr=False)

    def within_window(self, air_dt):
        return self.remonitor_window is None or (self.now - air_dt) <= self.remonitor_window

    def describe(self, sid, season, e, with_air_date=True):
        series_title = self.series_map.get(sid, "Unknown Series")
        episode_number = e.get("episodeNumber", "?")
        episode_title = e.get("title", "Unknown Title")
        text = f"{series_title} – S{season:02}E{episode_number:02} – {episode_title}"
        if with_air_date:
            text += f" (airDate: {e.get('airDateUtc')})"
        return text

    def unmonitor(self, sid, season, e, no_air_date=False):
        if no_air_date:
            log.info("UNMONITOR (no air date): %s", self.describe(sid, season, e, with_air_date=False))
        else:
            log.info("UNMONITOR: %s", self.describe(sid, season, e))
        self.eps_to_unmonitor.append(e["id"])
        self.episode_series[e["id"]] = sid
        if sid not in self.series_with_auto_tag:
            self.series_to_tag.add(sid)

    def monitored_after_pass(self, e):
        """Whether an episode will be monitored once this pass's changes are applied."""
        eid = e.get("id")
        if eid in self._unmonitor_set:
            return False
        return bool(e.get("monitored", False)) or eid in self._monitor_set

    def freeze(self):
        self._monitor_set = set(self.eps_to_monitor)
        self._unmonitor_set = set(self.eps_to_unmonitor)


def _process_standard(p, sid, season, eps, delay):
    """Decide each episode on its own air date."""
    for e in eps:
        air = e.get("airDateUtc")
        p.assessed += 1

        if Config.SKIP_IF_FILE and e.get("hasFile"):
            continue
        if not air:
            if e.get("monitored", False):
                p.unmonitor(sid, season, e, no_air_date=True)
            continue
        air_dt = _air_date(p, sid, season, e)
        if air_dt is None:
            continue

        threshold = air_dt + delay
        monitored = bool(e.get("monitored", False))

        if p.now >= threshold and not monitored:
            if sid in p.series_with_auto_tag and p.within_window(air_dt):
                log.info("MONITOR: %s", p.describe(sid, season, e))
                p.eps_to_monitor.append(e["id"])
                p.episode_series[e["id"]] = sid
        elif p.now < threshold and monitored:
            p.unmonitor(sid, season, e)


def _process_season_pack(p, sid, season, eps, delay):
    """Decide the whole season on its first aired episode (the trigger)."""
    trigger = next((e for e in sorted(eps, key=lambda x: x.get("episodeNumber", 999))
                    if e.get("airDateUtc")), None)
    if not trigger:
        return

    trigger_air = _air_date(p, sid, season, trigger)
    if trigger_air is None:
        return
    trigger_threshold = trigger_air + delay

    if p.now >= trigger_threshold:
        if not (sid in p.series_with_auto_tag and p.within_window(trigger_air)):
            return
        added = 0
        for e in eps:
            p.assessed += 1
            if not e.get("airDateUtc"):
                continue
            if Config.SKIP_IF_FILE and e.get("hasFile"):
                continue
            if not e.get("monitored", False):
                log.info("MONITOR (season pack): %s", p.describe(sid, season, e, with_air_date=False))
                p.eps_to_monitor.append(e["id"])
                p.episode_series[e["id"]] = sid
                added += 1
        if added > 0:
            log.info("SEASON PACK MODE: Re-monitored %d episodes for %s S%02d",
                     added, p.series_map.get(sid, "Unknown Series"), season)
        return

    # Trigger not reached yet: unmonitor anything still monitored in the season.
    # Note: compares against the trigger's threshold, not each episode's own.
    for e in eps:
        air = e.get("airDateUtc")
        p.assessed += 1
        if Config.SKIP_IF_FILE and e.get("hasFile"):
            continue
        if not air:
            if e.get("monitored", False):
                p.unmonitor(sid, season, e, no_air_date=True)
            continue
        if _air_date(p, sid, season, e) is None:
            continue
        if p.now < trigger_threshold and e.get("monitored", False):
            p.unmonitor(sid, season, e)


def _series_needs_tag(p, eps, delay):
    """True if any episode may still need re-monitoring, judged on state after this pass.

    Errs towards keeping the tag: removing it too early strands an episode unmonitored for
    good, while keeping it too long is harmless.
    """
    for e in eps:
        if p.monitored_after_pass(e):
            continue
        if Config.SKIP_IF_FILE and e.get("hasFile"):
            continue
        air_dt = arr_client.parse_iso(e.get("airDateUtc"))
        if air_dt is None:
            return True        # no air date yet; may get one later
        if air_dt > p.now:
            return True        # hasn't aired yet
        if p.now < air_dt + delay:
            return True        # aired, threshold not met yet
        if p.within_window(air_dt):
            return True        # could still be re-monitored
    return False


def _refresh_tba_series(series_episodes, series_map, eps_to_monitor, eps_to_unmonitor, now):
    """Trigger a Sonarr metadata refresh for series with recently-aired TBA episodes.

    Some shows don't publish episode titles to TheTVDB until after the episode
    airs. Sonarr's natural refresh cycle is ~12 hours, so a monitored episode can
    be grabbed and imported while its title is still "TBA", baking that into the
    filename. Nudging Sonarr to refresh gets the real title in before the import
    happens.

    TheTVDB often still reports TBA at the moment we re-monitor, so this retries on
    each run until the title lands or the episode falls outside _TBA_WINDOW.

    Returns the number of series refreshed.
    """
    monitored_now = set(eps_to_monitor)
    unmonitored_now = set(eps_to_unmonitor)
    refreshed = 0

    for sid, eps in series_episodes.items():
        series_title = series_map.get(sid, f"id:{sid}")
        tba_count = 0

        for e in eps:
            air_dt = arr_client.parse_iso(e.get("airDateUtc"))
            if air_dt is None:
                continue

            # Only episodes that have aired and are still within the refresh window
            if air_dt > now or (now - air_dt) > _TBA_WINDOW:
                continue

            # The cached episode dicts are pre-update, so episodes we re-monitored
            # this run still read monitored=False. That's the case we care about most.
            eid = e.get("id")
            if eid in unmonitored_now:
                continue
            if not (e.get("monitored", False) or eid in monitored_now):
                continue

            # Deliberately not filtered on hasFile - an already-imported TBA episode
            # still benefits from the real title reaching Sonarr's database.
            if _is_tba_title(e.get("title")):
                tba_count += 1

        if not tba_count:
            continue

        last = _tba_refresh_last.get(sid)
        if last is not None and (now - last) < _TBA_COOLDOWN:
            log.debug("TBA refresh on cooldown for %s (last %s)", series_title, last.isoformat())
            continue

        log.info("TBA REFRESH: %s (%d episode(s) with TBA titles)", series_title, tba_count)
        payload = {"name": "RefreshSeries", "seriesId": sid}
        try:
            _req("POST", "/api/v3/command", json=payload)  # logged, not sent, in a dry run
            # Record in dry-run too, so dry-run logs mirror live cadence
            _tba_refresh_last[sid] = now
            refreshed += 1
        except Exception as exc:
            # Don't let a failed refresh abort the run - run_once() would retry the
            # entire pass and redo every monitor/unmonitor PUT.
            log.warning("TBA refresh failed for %s: %s", series_title, str(exc))

    return refreshed


def _set_episodes_monitored(p, episode_ids, monitored):
    """One PUT for all episodes. On failure, the error names the series affected."""
    if not episode_ids:
        return
    try:
        _req("PUT", "/api/v3/episode/monitor", json={"episodeIds": episode_ids, "monitored": monitored})
    except arr_client.ArrApiError as e:
        ids = set(episode_ids)
        names = sorted({p.series_map.get(p.episode_series.get(eid), "unknown series") for eid in ids})
        shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
        action = "re-monitor" if monitored else "unmonitor"
        raise arr_client.ArrApiError(f"Couldn't {action} {len(ids)} episode(s) in {shown}: {e}",
                                     status_code=e.status_code, transient=e.transient) from e


def _apply(p, series_episodes, series_delay_override, default_delay):
    """Write this pass's decisions to Sonarr.

    Order matters, so a failure part-way can't strand an episode unmonitored without the
    auto-tag (it would never be re-monitored):
      1. tag series, then unmonitor their episodes
      2. re-monitor episodes, then remove tags that are no longer needed
    """
    failed = _edit_series_tags(p.series_to_tag, p.auto_tag_id, "add")
    for sid, err in failed.items():
        log.error("Couldn't add auto-tag to %s, leaving its episodes monitored: %s",
                  p.series_map.get(sid, f"id:{sid}"), err)
    if failed:
        p.eps_to_unmonitor = [eid for eid in p.eps_to_unmonitor if p.episode_series[eid] not in failed]
    p.series_with_auto_tag |= (p.series_to_tag - set(failed))

    _set_episodes_monitored(p, p.eps_to_unmonitor, False)
    _set_episodes_monitored(p, p.eps_to_monitor, True)

    # Every tagged series we looked at this pass is re-checked, so a removal that fails
    # (or a tag left behind by an older version) is cleaned up on a later pass
    p.freeze()
    to_untag = set()
    for sid in p.series_with_auto_tag & set(series_episodes):
        delay = series_delay_override.get(sid, default_delay)
        if _series_needs_tag(p, series_episodes[sid], delay):
            log.debug("Keeping auto-tag on %s (episodes still pending)", p.series_map.get(sid, f"id:{sid}"))
        else:
            log.info("Removing auto-tag from %s (nothing left to re-monitor)", p.series_map.get(sid, f"id:{sid}"))
            to_untag.add(sid)
    try:
        failed = _edit_series_tags(to_untag, p.auto_tag_id, "remove")
    except arr_client.ArrApiError as e:
        failed = {sid: e for sid in to_untag}
    for sid, err in failed.items():
        log.warning("Couldn't remove auto-tag from %s, will retry next run: %s",
                    p.series_map.get(sid, f"id:{sid}"), err)


def _run_once_inner():
    id_to_label, label_to_id = _tags_map()
    auto_tag_id = _ensure_tag(Config.AUTO_TAG_NAME, label_to_id)

    season_pack_tag_id = None
    if Config.SEASON_PACK_MODE:
        season_pack_tag_id = _ensure_tag(Config.SEASON_PACK_MODE_TAG, label_to_id)

    # 0 = disabled/unlimited
    remonitor_window = (timedelta(days=Config.SONARR_REMONITOR_WINDOW_DAYS)
                        if Config.SONARR_REMONITOR_WINDOW_DAYS > 0 else None)

    series = _get("/api/v3/series")
    series_map = {s["id"]: s["title"] for s in series}
    series_with_auto_tag = {s["id"] for s in series if auto_tag_id in s.get("tags", [])}

    season_pack_series = set()
    if Config.SEASON_PACK_MODE and season_pack_tag_id:
        season_pack_series = {s["id"] for s in series if season_pack_tag_id in s.get("tags", [])}

    series_delay_override = {}
    for s in series:
        override = _get_delay_override(s.get("tags", []), id_to_label, s.get("title", f"id:{s['id']}"))
        if override is not None:
            series_delay_override[s["id"]] = override

    # Every monitored season of every monitored series, excluding IGNORE_TAG_NAME
    ignore = (Config.IGNORE_TAG_NAME or "").lower()
    tracked = []
    for s in series:
        if not s.get("monitored"):
            continue
        if ignore and any(id_to_label.get(tid, "").lower() == ignore for tid in s.get("tags", [])):
            continue
        for season in s.get("seasons", []) or []:
            if season.get("monitored"):
                tracked.append((s["id"], season["seasonNumber"]))

    default_delay = timedelta(minutes=Config.DELAY_MINUTES)
    p = _Pass(
        now=datetime.now(timezone.utc),
        auto_tag_id=auto_tag_id,
        remonitor_window=remonitor_window,
        series_map=series_map,
        series_with_auto_tag=series_with_auto_tag,
    )
    series_episodes = {}  # sid -> every episode fetched for it this run

    for sid, season in tracked:
        eps = _get("/api/v3/episode", params={"seriesId": sid, "seasonNumber": season})
        series_episodes.setdefault(sid, []).extend(eps)
        delay = series_delay_override.get(sid, default_delay)

        if sid in season_pack_series:
            _process_season_pack(p, sid, season, eps, delay)
        else:
            _process_standard(p, sid, season, eps, delay)

    _apply(p, series_episodes, series_delay_override, default_delay)

    tba_refreshed = 0
    if Config.SONARR_REFRESH_TBA:
        tba_refreshed = _refresh_tba_series(series_episodes, series_map, p.eps_to_monitor, p.eps_to_unmonitor, p.now)

    managed = len(p.eps_to_monitor) + len(p.eps_to_unmonitor)
    log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d",
             p.assessed, managed, len(p.eps_to_unmonitor), len(p.eps_to_monitor))

    if tba_refreshed:
        log.info("TBA REFRESH SUMMARY: %d series refreshed", tba_refreshed)


def run_once():
    """Run one pass. Returns True on success, False on failure, None if skipped."""
    if not arr_client.is_configured("Sonarr", Config.ENABLE_SONARR, Config.SONARR_URL, Config.SONARR_API_KEY, log):
        return None
    log.info("Sonarr app starting…")
    return arr_client.run_with_retries(_run_once_inner, "Sonarr", log)


def run_sonarr():
    return run_once()
