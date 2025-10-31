import logging, json
from datetime import datetime, timedelta, timezone
import requests
from requests.exceptions import ReadTimeout
import time
from core.config import Config

log = logging.getLogger("radarr")

def _api(path: str) -> str:
    return f"{Config.RADARR_URL}{path}"

def _req(method: str, path: str, **kw):
    s = requests.Session()
    s.headers.update({"X-Api-Key": Config.RADARR_API_KEY})
    url = _api(path)
    if method.upper() in ("POST","PUT","PATCH","DELETE") and Config.DRY_RUN:
        payload = kw.get("json") or kw.get("data")
        log.info("[DRY] %s %s -> %s", method.upper(), path, json.dumps(payload) if payload else "(no body)")
        class Dummy:
            ok=True
            status_code=200
            def json(self): return {}
            text=""
        return Dummy()
    return s.request(method.upper(), url, timeout=30, **kw)

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

def _tags_map():
    r = _req("GET","/api/v3/tag")
    items = r.json() if hasattr(r, "json") else []
    return { int(t["id"]): t["label"] for t in items }, { t["label"].lower(): int(t["id"]) for t in items }

def _ensure_tag(label, label_to_id):
    if label.lower() in label_to_id:
        return label_to_id[label.lower()]
    if Config.DRY_RUN:
        log.info("[DRY] POST /api/v3/tag -> {\"label\": \"%s\"}", label)
        return 999999
    r = _req("POST","/api/v3/tag", json={"label": label})
    if r.ok:
        # refresh
        _, rev = _tags_map()
        return rev.get(label.lower())
    raise RuntimeError("Failed to ensure tag")

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
    delay = timedelta(minutes=Config.DELAY_MINUTES)
    now = datetime.now(timezone.utc)

    movies = _req("GET","/api/v3/movie").json()
    assessed = managed = unmonitored = remonitored = 0
    for m in movies:
        title = m.get("title", f"id:{m.get('id')}")
        if Config.IGNORE_TAG_NAME and any(id_to_label.get(tid,"").lower()==Config.IGNORE_TAG_NAME.lower() for tid in m.get("tags",[])):
            continue
        if Config.SKIP_IF_FILE and _has_file(m):
            continue

        release = _pick_release(m)
        if not release:
            log.debug("No usable release date for %s", title)
            continue
        threshold = release + delay
        monitored = bool(m.get("monitored", False))
        has_auto  = auto_tag_id in set(m.get("tags", []))

        assessed += 1

        if monitored and now < threshold:
            log.info("%sUNMONITOR: %s until %s", "[DRY] " if Config.DRY_RUN else "", title, threshold.isoformat())
            _set_monitored(int(m["id"]), False)
            _apply_tags(int(m["id"]), auto_tag_id, "add")
            managed += 1
            unmonitored += 1
        elif (not monitored) and has_auto and now >= threshold:
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


def run_job():
    log.info("Radarr job triggered via job queue")
    run_once()

# Export for external import
run_radarr = run_job
