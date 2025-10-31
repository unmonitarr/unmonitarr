

import logging
from common.logging_setup import setup_logging

# Set up logging once when this module is imported
setup_logging()

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger configured with our central logging settings.
    """
    return logging.getLogger(name)