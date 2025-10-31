import logging
import json as json_module
from datetime import datetime, timedelta, timezone
import requests
from core.config import Config
import time

log = logging.getLogger("sonarr")
AIR_FMT = "%Y-%m-%dT%H:%M:%SZ"

def _api(path:str)->str:
    return f"{Config.SONARR_URL}{path}"

def _req(method:str, path:str, **kw):
    s = requests.Session()
    s.headers.update({"X-Api-Key": Config.SONARR_API_KEY})
    url = _api(path)
    if method.upper() in ("POST","PUT","PATCH","DELETE") and Config.DRY_RUN:
        payload = kw.get("json") or kw.get("data")
        log.info("[DRY] %s %s -> %s", method.upper(), path, json_module.dumps(payload) if payload else "(no body)")
        class Dummy: ok=True; status_code=200; 
        def json(self): return {}; text=""
        return Dummy()
    return s.request(method.upper(), url, timeout=30, **kw)

def _tags_map():
    r = _req("GET","/api/v3/tag")
    items = r.json() if hasattr(r,"json") else []
    return { int(t["id"]): t["label"] for t in items }, { t["label"].lower(): int(t["id"]) for t in items }

def _ensure_tag(label, label_to_id):
    if label.lower() in label_to_id: return label_to_id[label.lower()]
    if Config.DRY_RUN:
        log.info("[DRY] POST /api/v3/tag -> {\"label\": \"%s\"}", label)
        return 999999
    r = _req("POST","/api/v3/tag", json={"label": label})
    if r.ok:
        _, rev = _tags_map()
        return rev.get(label.lower())
    raise RuntimeError("Failed to ensure tag")

def _run_once_inner():
    id_to_label, label_to_id = _tags_map()
    auto_tag_id = _ensure_tag(Config.AUTO_TAG_NAME, label_to_id)

    # Track all monitored series (latest season monitored), excluding IGNORE_TAG_NAME
    series = _req("GET","/api/v3/series").json()
    series_map = {s["id"]: s["title"] for s in series}
    tracked = []
    for s in series:
        if not s.get("monitored"): continue
        if Config.IGNORE_TAG_NAME and any(id_to_label.get(tid,"").lower()==Config.IGNORE_TAG_NAME.lower() for tid in s.get("tags",[])):
            continue
        seasons = s.get("seasons",[]) or []
        if not seasons: continue
        latest = max(seasons, key=lambda x: x.get("seasonNumber", -1))
        if not latest.get("monitored"): continue
        tracked.append((s["id"], latest["seasonNumber"]))
    assessed = 0

    delay = timedelta(minutes=Config.DELAY_MINUTES)
    now = datetime.now(timezone.utc)

    eps_to_monitor = []
    eps_to_unmonitor = []

    for sid, season in tracked:
        eps = _req("GET","/api/v3/episode", params={"seriesId": sid, "seasonNumber": season}).json()
        for e in eps:
            air = e.get("airDateUtc")
            if not air:
                continue
            assessed += 1
            try:
                air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if Config.SKIP_IF_FILE and e.get("hasFile"):
                continue
            threshold = air_dt + delay
            monitored = bool(e.get("monitored", False))
            series_title = series_map.get(sid, "Unknown Series")
            season_number = season
            episode_number = e.get("episodeNumber", "?")
            episode_title = e.get("title", "Unknown Title")
            formatted = f"{series_title} – S{season_number:02}E{episode_number:02} – {episode_title} (airDate: {air})"
            if air_dt <= now and now >= threshold and not monitored:
                log.info("MONITOR: %s", formatted)
                eps_to_monitor.append(e["id"])
            elif air_dt > now and monitored:
                log.info("UNMONITOR: %s", formatted)
                eps_to_unmonitor.append(e["id"])
                # Ensure the auto-unmonitored tag is applied to the parent series
                if not Config.DRY_RUN:
                    s = _req("GET", f"/api/v3/series/{sid}").json()
                    if auto_tag_id not in s.get("tags", []):
                        tags = s.get("tags", []) + [auto_tag_id]
                        _req("PUT", f"/api/v3/series/{sid}", json={"tags": tags})

    if eps_to_unmonitor:
        if Config.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s", json_module.dumps({"episodeIds": eps_to_unmonitor, "monitored": False}))
        else:
            _req("PUT","/api/v3/episode/monitor", json={"episodeIds": eps_to_unmonitor, "monitored": False})
    if eps_to_monitor:
        if Config.DRY_RUN:
            log.info("[DRY] PUT /api/v3/episode/monitor -> %s", json_module.dumps({"episodeIds": eps_to_monitor, "monitored": True}))
        else:
            _req("PUT","/api/v3/episode/monitor", json={"episodeIds": eps_to_monitor, "monitored": True})

    if eps_to_monitor or eps_to_unmonitor:
        log.info("SUMMARY: Assessed %d, Managed %d, Unmonitored %d, Monitored %d", assessed, len(eps_to_monitor) + len(eps_to_unmonitor), len(eps_to_unmonitor), len(eps_to_monitor))
    else:
        log.info("SUMMARY: Assessed %d, Managed 0, Unmonitored 0, Monitored 0", assessed)

def run_once():
    log.info("Sonarr app starting…")
    if not (Config.ENABLE_SONARR and Config.SONARR_URL and Config.SONARR_API_KEY):
        return

    last_err = None
    for attempt in range(1, 4):
        try:
            _run_once_inner()
            return
        except Exception as e:
            last_err = e
            if attempt < 3:
                log.warning("Attempt %d/3 failed: %s", attempt, str(e))
                time.sleep(5)
            else:
                log.error("Failed after 3 attempts: %s", str(e))

def run_job():
    run_once()
