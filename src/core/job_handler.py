import logging
from core.config import Config

log = logging.getLogger("runner")

def get_enabled_apps():
    """Reads config and returns a list of enabled apps"""
    enabled_apps = []
    if Config.ENABLE_RADARR:
        enabled_apps.append("radarr")
    if Config.ENABLE_SONARR:
        enabled_apps.append("sonarr")
    log.debug(f"Enabled apps: {enabled_apps}")
    return enabled_apps

def initialise_environment():
    """Initialize environment and return enabled apps"""
    log.debug("Initialising job environment.")
    enabled_apps = get_enabled_apps()
    if not enabled_apps:
        log.warning("No apps enabled! Check ENABLE_RADARR and ENABLE_SONARR settings.")
    return enabled_apps
