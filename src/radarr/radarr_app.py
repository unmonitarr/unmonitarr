import time
from datetime import datetime, timedelta, timezone

from requests.exceptions import ReadTimeout

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
    """Return a timedelta override if a delayby_<N> tag is found, else None."""
    return arr_client.get_delay_override(tag_ids, id_to_label, title, log)


def _parse_iso(s):
    if not s: return None
    s = s.strip()
    if s.endswith("Z"): s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None

def _pick_release(movie):
    digital  = _parse_iso(movie.get("digitalRelease"))
    physical = _parse_iso(movie.get("physicalRelease"))
    cinemas  = _parse_iso(movie.get("inCinemas"))

    if Config.PREFERRED_RELEASE == "digital":
        return digital or physical or (None if Config.IGNORE_INCINEMAS else cinemas)
    if Config.PREFERRED_RELEASE == "physical":
        return physical or digital or (None if Config.IGNORE_INCINEMAS else cinemas)
    # either
    candidates = [d for d in (digital, physical) if d]
    if candidates: return min(candidates)
    return None if Config.IGNORE_INCINEMAS else cinemas

def _has_file(movie):
    if "hasFile" in movie: return bool(movie["hasFile"])
    return bool(movie.get("movieFile"))

def _apply_tags(movie_id, tag_id, mode):
    payload = {"movieIds":[movie_id], "tags":[tag_id], "applyTags": mode}
    _req("PUT","/api/v3/movie/editor", json=payload)

def _set_monitored(movie_id, monitored):
    _req("PUT","/api/v3/movie/editor", json={"movieIds":[movie_id], "monitored": monitored})

def _run_once():
    if not (Config.ENABLE_RADARR and Config.RADARR_URL and Config.RADARR_API_KEY):
        return

    log.info("Radarr app starting…")

    id_to_label, label_to_id = _tags_map()
    auto_tag_id = _ensure_tag(Config.AUTO_TAG_NAME, label_to_id)
    default_delay = timedelta(minutes=Config.DELAY_MINUTES)
    remonitor_window = timedelta(days=Config.RADARR_REMONITOR_WINDOW_DAYS) if Config.RADARR_REMONITOR_WINDOW_DAYS > 0 else None
    now = datetime.now(timezone.utc)

    movies = _req("GET","/api/v3/movie").json()
    assessed = managed = unmonitored = remonitored = 0
    for m in movies:
        title = m.get("title", f"id:{m.get('id')}")
        if Config.IGNORE_TAG_NAME and any(id_to_label.get(tid,"").lower()==Config.IGNORE_TAG_NAME.lower() for tid in m.get("tags",[])):
            continue
        if Config.SKIP_IF_FILE and _has_file(m):
            continue

        delay = _get_delay_override(m.get("tags", []), id_to_label, title) or default_delay
        release = _pick_release(m)
        monitored = bool(m.get("monitored", False))
        has_auto  = auto_tag_id in set(m.get("tags", []))

        assessed += 1

        # Handle items without release dates
        if not release:
            if monitored:
                log.info("%sUNMONITOR (no release date): %s", "[DRY] " if Config.DRY_RUN else "", title)
                _set_monitored(int(m["id"]), False)
                _apply_tags(int(m["id"]), auto_tag_id, "add")
                managed += 1
                unmonitored += 1
            continue

        threshold = release + delay

        if monitored and now < threshold:
            log.info("%sUNMONITOR: %s until %s", "[DRY] " if Config.DRY_RUN else "", title, threshold.isoformat())
            _set_monitored(int(m["id"]), False)
            _apply_tags(int(m["id"]), auto_tag_id, "add")
            managed += 1
            unmonitored += 1
        elif (not monitored) and has_auto and now >= threshold:
            # Check if within re-monitoring window (if enabled)
            within_window = True
            if remonitor_window is not None:
                within_window = (now - release) <= remonitor_window

            if within_window:
                log.info("%sMONITOR: %s (past %s)", "[DRY] " if Config.DRY_RUN else "", title, threshold.isoformat())
                _set_monitored(int(m["id"]), True)
                _apply_tags(int(m["id"]), auto_tag_id, "remove")
                managed += 1
                remonitored += 1
    log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d", assessed, managed, unmonitored, remonitored)

def run_once():
    if not (Config.ENABLE_RADARR and Config.RADARR_URL and Config.RADARR_API_KEY):
        return

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            _run_once()
            break
        except ReadTimeout as e:
            if attempt < max_retries:
                log.warning("Retrying after timeout… (attempt %d)", attempt)
                time.sleep(5)
            else:
                log.error("Failed after 3 attempts: %s", e)


def run_radarr():
    log.info("Radarr job triggered via job queue")
    run_once()
