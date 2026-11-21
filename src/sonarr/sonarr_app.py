import json as json_module
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

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


def _tag_series(sid, auto_tag_id):
    """Make sure the auto-tag is on a series. Live runs only."""
    if Config.DRY_RUN:
        return
    s = _req("GET", f"/api/v3/series/{sid}").json()
    if auto_tag_id not in s.get("tags", []):
        s["tags"] = s.get("tags", []) + [auto_tag_id]
        _req("PUT", f"/api/v3/series/{sid}", json=s)


def _untag_series(sid, auto_tag_id):
    s = _req("GET", f"/api/v3/series/{sid}").json()
    if auto_tag_id in s.get("tags", []):
        s["tags"] = [t for t in s.get("tags", []) if t != auto_tag_id]
        _req("PUT", f"/api/v3/series/{sid}", json=s)


def _parse_air(air):
    return datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)


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
    remonitor_window: timedelta  # None = unlimited
    series_map: dict
    series_with_auto_tag: set
    eps_to_monitor: list = field(default_factory=list)
    eps_to_unmonitor: list = field(default_factory=list)
    series_to_remove_tag: set = field(default_factory=set)
    assessed: int = 0

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
        _tag_series(sid, self.auto_tag_id)


def _process_standard(p, sid, season, eps, delay):
    """Decide each episode on its own air date."""
    for e in eps:
        air = e.get("airDateUtc")
        p.assessed += 1

        if not air:
            if e.get("monitored", False):
                p.unmonitor(sid, season, e, no_air_date=True)
            continue
        try:
            air_dt = _parse_air(air)
        except Exception:
            continue
        if Config.SKIP_IF_FILE and e.get("hasFile"):
            continue

        threshold = air_dt + delay
        monitored = bool(e.get("monitored", False))

        if p.now >= threshold and not monitored:
            if sid in p.series_with_auto_tag and p.within_window(air_dt):
                log.info("MONITOR: %s", p.describe(sid, season, e))
                p.eps_to_monitor.append(e["id"])
                p.series_to_remove_tag.add(sid)
        elif p.now < threshold and monitored:
            p.unmonitor(sid, season, e)


def _process_season_pack(p, sid, season, eps, delay):
    """Decide the whole season on its first aired episode (the trigger)."""
    trigger = next((e for e in sorted(eps, key=lambda x: x.get("episodeNumber", 999))
                    if e.get("airDateUtc")), None)
    if not trigger:
        return

    trigger_air = _parse_air(trigger["airDateUtc"])
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
                added += 1
        if added > 0:
            log.info("SEASON PACK MODE: Re-monitored %d episodes for %s S%02d",
                     added, p.series_map.get(sid, "Unknown Series"), season)
            p.series_to_remove_tag.add(sid)
        return

    # Trigger not reached yet: unmonitor anything still monitored in the season.
    # Note: compares against the trigger's threshold, and doesn't check SKIP_IF_FILE.
    for e in eps:
        air = e.get("airDateUtc")
        p.assessed += 1
        if not air:
            if e.get("monitored", False):
                p.unmonitor(sid, season, e, no_air_date=True)
            continue
        try:
            _parse_air(air)
        except Exception:
            continue
        if p.now < trigger_threshold and e.get("monitored", False):
            p.unmonitor(sid, season, e)


def _series_needs_tag(p, eps, delay):
    """True if any episode could still need re-monitoring later."""
    for e in eps:
        if e.get("monitored", False):
            continue
        if Config.SKIP_IF_FILE and e.get("hasFile"):
            continue
        air = e.get("airDateUtc")
        if not air:
            continue
        try:
            air_dt = _parse_air(air)
        except Exception:
            continue
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
            air = e.get("airDateUtc")
            if not air:
                continue
            try:
                air_dt = _parse_air(air)
            except Exception:
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
            if Config.DRY_RUN:
                log.info("[DRY] POST /api/v3/command -> %s", json_module.dumps(payload))
            else:
                _req("POST", "/api/v3/command", json=payload)
            # Record in dry-run too, so dry-run logs mirror live cadence
            _tba_refresh_last[sid] = now
            refreshed += 1
        except Exception as exc:
            # Don't let a failed refresh abort the run - run_once() would retry the
            # entire pass and redo every monitor/unmonitor PUT.
            log.warning("TBA refresh failed for %s: %s", series_title, str(exc))

    return refreshed


def _run_once_inner():
    id_to_label, label_to_id = _tags_map()
    auto_tag_id = _ensure_tag(Config.AUTO_TAG_NAME, label_to_id)

    season_pack_tag_id = None
    if Config.SEASON_PACK_MODE:
        season_pack_tag_id = _ensure_tag(Config.SEASON_PACK_MODE_TAG, label_to_id)

    # 0 = disabled/unlimited
    remonitor_window = (timedelta(days=Config.SONARR_REMONITOR_WINDOW_DAYS)
                        if Config.SONARR_REMONITOR_WINDOW_DAYS > 0 else None)

    series = _req("GET", "/api/v3/series").json()
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
        eps = _req("GET", "/api/v3/episode", params={"seriesId": sid, "seasonNumber": season}).json()
        series_episodes.setdefault(sid, []).extend(eps)
        delay = series_delay_override.get(sid, default_delay)

        if sid in season_pack_series:
            try:
                _process_season_pack(p, sid, season, eps, delay)
            except Exception:
                continue
        else:
            _process_standard(p, sid, season, eps, delay)

    if p.eps_to_unmonitor:
        if Config.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s",
                     json_module.dumps({"episodeIds": p.eps_to_unmonitor, "monitored": False}))
        else:
            _req("PUT", "/api/v3/episode/monitor", json={"episodeIds": p.eps_to_unmonitor, "monitored": False})
    if p.eps_to_monitor:
        if Config.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s",
                     json_module.dumps({"episodeIds": p.eps_to_monitor, "monitored": True}))
        else:
            _req("PUT", "/api/v3/episode/monitor", json={"episodeIds": p.eps_to_monitor, "monitored": True})

    tba_refreshed = 0
    if Config.SONARR_REFRESH_TBA:
        tba_refreshed = _refresh_tba_series(series_episodes, series_map, p.eps_to_monitor, p.eps_to_unmonitor, p.now)

    # Remove the auto-tag from series that had episodes re-monitored, unless some
    # episode could still need re-monitoring later
    for sid in p.series_to_remove_tag:
        delay = series_delay_override.get(sid, default_delay)
        if _series_needs_tag(p, series_episodes.get(sid, []), delay):
            log.info("Keeping auto-tag on series (episodes still need re-monitoring): %s",
                     series_map.get(sid, f"id:{sid}"))
        elif Config.DRY_RUN:
            log.info("[DRY] Removing auto-tag from series: %s", series_map.get(sid, f"id:{sid}"))
        else:
            _untag_series(sid, auto_tag_id)

    managed = len(p.eps_to_monitor) + len(p.eps_to_unmonitor)
    log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d",
             p.assessed, managed, len(p.eps_to_unmonitor), len(p.eps_to_monitor))

    if tba_refreshed:
        log.info("TBA REFRESH SUMMARY: %d series refreshed", tba_refreshed)


def run_once():
    log.info("Sonarr app starting…")
    if not (Config.ENABLE_SONARR and Config.SONARR_URL and Config.SONARR_API_KEY):
        return

    for attempt in range(1, 4):
        try:
            _run_once_inner()
            return
        except Exception as e:
            if attempt < 3:
                log.warning("Attempt %d/3 failed: %s", attempt, str(e))
                time.sleep(5)
            else:
                log.error("Failed after 3 attempts: %s", str(e))


def run_sonarr():
    run_once()
