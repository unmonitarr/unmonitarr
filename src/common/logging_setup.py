import logging
from core.config import Config

def setup_logging():
    logging.basicConfig(
        level=Config.LOG_LEVEL,
        format="%(asctime)s %(levelname)s:%(name)s:%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )