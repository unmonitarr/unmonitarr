import os
import logging

def env_bool(name: str, default: str="0") -> bool:
    return os.environ.get(name, default).lower() in ("1","true","yes","on")

def env_int(name: str, default: str="0") -> int:
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return int(default)

class Config:
    # General
    TZ                 = os.environ.get("TZ", "UTC")
    SLEEP_MINUTES      = env_int("SLEEP_MINUTES", "30")  # loop interval
    AUTO_TAG_NAME      = os.environ.get("AUTO_TAG_NAME", "auto-unmonitored")
    IGNORE_TAG_NAME    = os.environ.get("IGNORE_TAG_NAME", "ignore")
    DELAY_MINUTES      = env_int("DELAY_MINUTES", "120")
    SKIP_IF_FILE       = env_bool("SKIP_IF_FILE", "1")

    # Radarr
    ENABLE_RADARR      = env_bool("ENABLE_RADARR", "1")
    RADARR_URL         = os.environ.get("RADARR_URL", "").rstrip("/")
    RADARR_API_KEY     = os.environ.get("RADARR_API_KEY", "")
    PREFERRED_RELEASE  = os.environ.get("PREFERRED_RELEASE", "either").lower()  # digital|physical|either
    IGNORE_INCINEMAS   = env_bool("IGNORE_INCINEMAS", "0")

    # Sonarr
    ENABLE_SONARR         = env_bool("ENABLE_SONARR", "1")
    SONARR_URL            = os.environ.get("SONARR_URL", "").rstrip("/")
    SONARR_API_KEY        = os.environ.get("SONARR_API_KEY", "")
    SEASON_PACK_MODE      = env_bool("SEASON_PACK_MODE", "0")
    SEASON_PACK_MODE_TAG  = os.environ.get("SEASON_PACK_MODE_TAG", "season-pack")

    # Re-monitoring windows (0 = disabled/unlimited)
    RADARR_REMONITOR_WINDOW_DAYS = env_int("RADARR_REMONITOR_WINDOW_DAYS", "30")
    SONARR_REMONITOR_WINDOW_DAYS = env_int("SONARR_REMONITOR_WINDOW_DAYS", "14")

    # Dry run
    DRY_RUN            = env_bool("DRY_RUN", "1")

    # Logging
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return hasattr(self, key)


log = logging.getLogger("config")
log.setLevel(Config.LOG_LEVEL)
log.debug(f"Log level set to: {Config.LOG_LEVEL}")

CONFIG = Config()
