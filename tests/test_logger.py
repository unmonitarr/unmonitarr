import logging
from common.logger import get_logger

def test_logger_basic_usage(caplog):
    logger = get_logger('test_logger')
    with caplog.at_level(logging.INFO):
        logger.info('This is a test log message.')

    assert 'This is a test log message.' in caplog.text
