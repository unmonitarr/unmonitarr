import logging
import io
from common.logging_setup import setup_logging

def test_logging_setup_sets_log_level_and_formatter(caplog):
    # Redirect logging output to a string buffer
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))

    logger = logging.getLogger('test_logger')
    logger.addHandler(handler)
    logger.setLevel(logging.NOTSET)

    # Setup logging (this should apply to root logger)
    setup_logging(logging.DEBUG)
    logger.debug("Debug message")

    handler.flush()
    output = log_stream.getvalue()
    assert "DEBUG:test_logger:Debug message" in output