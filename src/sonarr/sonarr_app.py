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

    # Get season pack mode tag ID if feature is enabled
    season_pack_tag_id = None
    if Config.SEASON_PACK_MODE:
        season_pack_tag_id = _ensure_tag(Config.SEASON_PACK_MODE_TAG, label_to_id)

    # Set up re-monitoring window (0 = disabled/unlimited)
    remonitor_window = timedelta(days=Config.SONARR_REMONITOR_WINDOW_DAYS) if Config.SONARR_REMONITOR_WINDOW_DAYS > 0 else None

    # Track all monitored series (latest season monitored), excluding IGNORE_TAG_NAME
    series = _req("GET","/api/v3/series").json()
    series_map = {s["id"]: s["title"] for s in series}

    # Track which series have the auto-unmonitored tag
    series_with_auto_tag = set()
    for s in series:
        if auto_tag_id in s.get("tags", []):
            series_with_auto_tag.add(s["id"])

    # Track which series have season pack mode enabled
    season_pack_series = set()
    if Config.SEASON_PACK_MODE and season_pack_tag_id:
        for s in series:
            if season_pack_tag_id in s.get("tags", []):
                season_pack_series.add(s["id"])

    tracked = []
    for s in series:
        if not s.get("monitored"): continue
        if Config.IGNORE_TAG_NAME and any(id_to_label.get(tid,"").lower()==Config.IGNORE_TAG_NAME.lower() for tid in s.get("tags",[])):
            continue
        seasons = s.get("seasons",[]) or []
        if not seasons: continue
        # Process all monitored seasons, not just the latest
        for season in seasons:
            if season.get("monitored"):
                tracked.append((s["id"], season["seasonNumber"]))
    assessed = 0

    delay = timedelta(minutes=Config.DELAY_MINUTES)
    now = datetime.now(timezone.utc)

    eps_to_monitor = []
    eps_to_unmonitor = []
    series_to_remove_tag = set()  # Track series that should have auto-tag removed
    series_episodes_to_check = {}  # Track all episodes per series for tag removal logic

    for sid, season in tracked:
        eps = _req("GET","/api/v3/episode", params={"seriesId": sid, "seasonNumber": season}).json()

        # Store episodes for this series for later tag removal check
        if sid not in series_episodes_to_check:
            series_episodes_to_check[sid] = []
        series_episodes_to_check[sid].extend(eps)

        # Check if this series has season pack mode enabled
        use_season_pack_mode = sid in season_pack_series

        if use_season_pack_mode:
            # Season pack mode: Find trigger episode and potentially monitor entire season
            trigger_episode = None

            # Find Episode 1 or first episode with air date
            for e in sorted(eps, key=lambda x: x.get("episodeNumber", 999)):
                if e.get("airDateUtc"):
                    trigger_episode = e
                    break

            if trigger_episode:
                air = trigger_episode.get("airDateUtc")
                try:
                    air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                    threshold = air_dt + delay

                    # Check if trigger episode threshold has been met
                    if air_dt <= now and now >= threshold:
                        # Check auto-tag and time window for season pack mode
                        has_auto_tag = sid in series_with_auto_tag
                        within_window = True
                        if remonitor_window is not None:
                            within_window = (now - air_dt) <= remonitor_window

                        if has_auto_tag and within_window:
                            # Re-monitor all episodes in this season (excluding those with files or no air dates)
                            season_episodes_added = 0
                            for e in eps:
                                assessed += 1
                                # Skip episodes without air dates
                                if not e.get("airDateUtc"):
                                    continue
                                if Config.SKIP_IF_FILE and e.get("hasFile"):
                                    continue
                                if not e.get("monitored", False):
                                    series_title = series_map.get(sid, "Unknown Series")
                                    episode_number = e.get("episodeNumber", "?")
                                    episode_title = e.get("title", "Unknown Title")
                                    formatted = f"{series_title} – S{season:02}E{episode_number:02} – {episode_title}"
                                    log.info("MONITOR (season pack): %s", formatted)
                                    eps_to_monitor.append(e["id"])
                                    season_episodes_added += 1

                            if season_episodes_added > 0:
                                series_title = series_map.get(sid, "Unknown Series")
                                log.info("SEASON PACK MODE: Re-monitored %d episodes for %s S%02d",
                                       season_episodes_added, series_title, season)
                                series_to_remove_tag.add(sid)
                    else:
                        # Still before trigger - unmonitor any monitored future episodes
                        for e in eps:
                            air = e.get("airDateUtc")
                            assessed += 1

                            # Handle episodes without air dates
                            if not air:
                                if e.get("monitored", False):
                                    series_title = series_map.get(sid, "Unknown Series")
                                    episode_number = e.get("episodeNumber", "?")
                                    episode_title = e.get("title", "Unknown Title")
                                    formatted = f"{series_title} – S{season:02}E{episode_number:02} – {episode_title}"
                                    log.info("UNMONITOR (no air date): %s", formatted)
                                    eps_to_unmonitor.append(e["id"])
                                    # Ensure the auto-unmonitored tag is applied to the parent series
                                    if not Config.DRY_RUN:
                                        s = _req("GET", f"/api/v3/series/{sid}").json()
                                        if auto_tag_id not in s.get("tags", []):
                                            s["tags"] = s.get("tags", []) + [auto_tag_id]
                                            _req("PUT", f"/api/v3/series/{sid}", json=s)
                                continue
                            try:
                                air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                            except Exception:
                                continue
                            if air_dt > now and e.get("monitored", False):
                                series_title = series_map.get(sid, "Unknown Series")
                                episode_number = e.get("episodeNumber", "?")
                                episode_title = e.get("title", "Unknown Title")
                                formatted = f"{series_title} – S{season:02}E{episode_number:02} – {episode_title} (airDate: {air})"
                                log.info("UNMONITOR: %s", formatted)
                                eps_to_unmonitor.append(e["id"])
                                # Ensure the auto-unmonitored tag is applied to the parent series
                                if not Config.DRY_RUN:
                                    s = _req("GET", f"/api/v3/series/{sid}").json()
                                    if auto_tag_id not in s.get("tags", []):
                                        s["tags"] = s.get("tags", []) + [auto_tag_id]
                                        _req("PUT", f"/api/v3/series/{sid}", json=s)
                except Exception:
                    continue
        else:
            # Standard mode: Process each episode individually
            for e in eps:
                air = e.get("airDateUtc")
                assessed += 1

                # Handle episodes without air dates
                if not air:
                    if e.get("monitored", False):
                        series_title = series_map.get(sid, "Unknown Series")
                        episode_number = e.get("episodeNumber", "?")
                        episode_title = e.get("title", "Unknown Title")
                        formatted = f"{series_title} – S{season:02}E{episode_number:02} – {episode_title}"
                        log.info("UNMONITOR (no air date): %s", formatted)
                        eps_to_unmonitor.append(e["id"])
                        # Ensure the auto-unmonitored tag is applied to the parent series
                        if not Config.DRY_RUN:
                            s = _req("GET", f"/api/v3/series/{sid}").json()
                            if auto_tag_id not in s.get("tags", []):
                                s["tags"] = s.get("tags", []) + [auto_tag_id]
                                _req("PUT", f"/api/v3/series/{sid}", json=s)
                    continue
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

                # Re-monitoring logic: Check auto-tag, threshold, and time window
                if air_dt <= now and now >= threshold and not monitored:
                    has_auto_tag = sid in series_with_auto_tag
                    within_window = True
                    if remonitor_window is not None:
                        within_window = (now - air_dt) <= remonitor_window

                    if has_auto_tag and within_window:
                        log.info("MONITOR: %s", formatted)
                        eps_to_monitor.append(e["id"])
                        series_to_remove_tag.add(sid)
                elif air_dt > now and monitored:
                    log.info("UNMONITOR: %s", formatted)
                    eps_to_unmonitor.append(e["id"])
                    # Ensure the auto-unmonitored tag is applied to the parent series
                    if not Config.DRY_RUN:
                        s = _req("GET", f"/api/v3/series/{sid}").json()
                        if auto_tag_id not in s.get("tags", []):
                            s["tags"] = s.get("tags", []) + [auto_tag_id]
                            _req("PUT", f"/api/v3/series/{sid}", json=s)

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

    # Remove auto-tag from series that had episodes re-monitored
    # BUT only if there are no remaining episodes that still need re-monitoring
    for sid in series_to_remove_tag:
        # Check if any episodes in this series still need re-monitoring
        should_keep_tag = False

        if sid in series_episodes_to_check:
            for e in series_episodes_to_check[sid]:
                # Skip if episode is monitored (already handled)
                if e.get("monitored", False):
                    continue

                # Skip if episode has a file (won't re-monitor anyway due to SKIP_IF_FILE)
                if Config.SKIP_IF_FILE and e.get("hasFile"):
                    continue

                # Skip if no air date (won't re-monitor)
                air = e.get("airDateUtc")
                if not air:
                    continue

                # Check if episode could be re-monitored in the future
                try:
                    air_dt = datetime.strptime(air, AIR_FMT).replace(tzinfo=timezone.utc)
                    threshold = air_dt + delay

                    # Keep tag if episode hasn't aired yet (will need re-monitoring later)
                    if air_dt > now:
                        should_keep_tag = True
                        break

                    # Keep tag if episode has aired but threshold not met yet
                    if now < threshold:
                        should_keep_tag = True
                        break

                    # Episode has aired and threshold met - check if within window
                    within_window = True
                    if remonitor_window is not None:
                        within_window = (now - air_dt) <= remonitor_window

                    # Keep tag if episode is within window (could still be re-monitored)
                    if within_window:
                        should_keep_tag = True
                        break
                except Exception:
                    continue

        if should_keep_tag:
            log.info("Keeping auto-tag on series (episodes still need re-monitoring): %s", series_map.get(sid, f"id:{sid}"))
        else:
            if Config.DRY_RUN:
                log.info("[DRY] Removing auto-tag from series: %s", series_map.get(sid, f"id:{sid}"))
            else:
                s = _req("GET", f"/api/v3/series/{sid}").json()
                if auto_tag_id in s.get("tags", []):
                    s["tags"] = [t for t in s.get("tags", []) if t != auto_tag_id]
                    _req("PUT", f"/api/v3/series/{sid}", json=s)

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
