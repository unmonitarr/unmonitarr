from datetime import datetime, timedelta, timezone

from common import arr_client
from common.logger import get_logger
from core.config import Config

log = get_logger("radarr")


def _req(method: str, path: str, **kw):
    return arr_client.request(Config.RADARR_URL, Config.RADARR_API_KEY, method, path,
                              dry_run=Config.DRY_RUN, log=log, **kw)


def _tags_map():
    return arr_client.fetch_tags(_req)


def _ensure_tag(label, label_to_id):
    return arr_client.ensure_tag(_req, label, label_to_id, dry_run=Config.DRY_RUN, log=log)


def _get_delay_override(tag_ids, id_to_label, title="unknown"):
    """Return a timedelta override from a delayby-<N> (or legacy delayby_<N>) tag, else None."""
    return arr_client.get_delay_override(tag_ids, id_to_label, title, log)


def _get(path, **kw):
    return arr_client.get_json(_req, path, **kw)


# With no digital or physical date, treat a movie as released this long after it opens
# in cinemas. Matches Radarr's own Minimum Availability = Released. Re-monitoring on the
# cinema date itself would open the door right when only cam rips and fakes exist.
CINEMA_FALLBACK = timedelta(days=90)


def _pick_release(movie):
    digital  = arr_client.parse_iso(movie.get("digitalRelease"))
    physical = arr_client.parse_iso(movie.get("physicalRelease"))
    cinemas  = arr_client.parse_iso(movie.get("inCinemas"))
    fallback = None if (Config.IGNORE_INCINEMAS or cinemas is None) else cinemas + CINEMA_FALLBACK

    if Config.PREFERRED_RELEASE == "digital":
        return digital or physical or fallback
    if Config.PREFERRED_RELEASE == "physical":
        return physical or digital or fallback
    # either
    candidates = [d for d in (digital, physical) if d]
    if candidates:
        return min(candidates)
    return fallback

def _has_file(movie):
    if "hasFile" in movie: return bool(movie["hasFile"])
    return bool(movie.get("movieFile"))

def _edit_movies(movie_ids, monitored, tag_id, apply_tags):
    """Set monitored and add/remove the auto-tag in one call, so the two can't drift apart.

    Returns {movie_id: error} for movies that couldn't be changed.
    """
    return arr_client.bulk_edit(_req, "/api/v3/movie/editor", "movieIds", movie_ids,
                                {"monitored": monitored, "tags": [tag_id], "applyTags": apply_tags})


def _run_once():
    id_to_label, label_to_id = _tags_map()
    auto_tag_id = _ensure_tag(Config.AUTO_TAG_NAME, label_to_id)
    default_delay = timedelta(minutes=Config.DELAY_MINUTES)
    remonitor_window = timedelta(days=Config.RADARR_REMONITOR_WINDOW_DAYS) if Config.RADARR_REMONITOR_WINDOW_DAYS > 0 else None
    now = datetime.now(timezone.utc)
    ignore = (Config.IGNORE_TAG_NAME or "").lower()
    dry = "[DRY] " if Config.DRY_RUN else ""

    movies = _get("/api/v3/movie")
    titles = {}
    to_unmonitor, to_remonitor = [], []
    assessed = 0
    for m in movies:
        title = m.get("title", f"id:{m.get('id')}")
        titles[int(m["id"])] = title
        if ignore and any(id_to_label.get(tid, "").lower() == ignore for tid in m.get("tags", [])):
            continue
        if Config.SKIP_IF_FILE and _has_file(m):
            continue

        override = _get_delay_override(m.get("tags", []), id_to_label, title)
        delay = override if override is not None else default_delay
        release = _pick_release(m)
        monitored = bool(m.get("monitored", False))
        has_auto = auto_tag_id in set(m.get("tags", []))

        assessed += 1

        if not release:
            if monitored:
                log.info("%sUNMONITOR (no release date): %s", dry, title)
                to_unmonitor.append(int(m["id"]))
            continue

        threshold = release + delay

        if monitored and now < threshold:
            log.info("%sUNMONITOR: %s until %s", dry, title, threshold.isoformat())
            to_unmonitor.append(int(m["id"]))
        elif (not monitored) and has_auto and now >= threshold:
            if remonitor_window is None or (now - release) <= remonitor_window:
                log.info("%sMONITOR: %s (past %s)", dry, title, threshold.isoformat())
                to_remonitor.append(int(m["id"]))

    failed_unmonitor = _edit_movies(to_unmonitor, False, auto_tag_id, "add")
    for mid, err in failed_unmonitor.items():
        log.error("Couldn't unmonitor %s: %s", titles.get(mid, f"id:{mid}"), err)
    failed_remonitor = _edit_movies(to_remonitor, True, auto_tag_id, "remove")
    for mid, err in failed_remonitor.items():
        log.error("Couldn't re-monitor %s: %s", titles.get(mid, f"id:{mid}"), err)

    unmonitored = len(to_unmonitor) - len(failed_unmonitor)
    remonitored = len(to_remonitor) - len(failed_remonitor)
    log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d",
             assessed, unmonitored + remonitored, unmonitored, remonitored)
    if failed_unmonitor or failed_remonitor:
        log.warning("%d movie(s) couldn't be updated, see errors above",
                    len(failed_unmonitor) + len(failed_remonitor))


def run_once():
    """Run one pass. Returns True on success, False on failure, None if skipped."""
    if not arr_client.is_configured("Radarr", Config.ENABLE_RADARR, Config.RADARR_URL, Config.RADARR_API_KEY, log):
        return None
    log.info("Radarr app starting…")
    return arr_client.run_with_retries(_run_once, "Radarr", log)


def run_radarr():
    return run_once()
