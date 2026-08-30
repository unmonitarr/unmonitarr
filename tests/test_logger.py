import logging
import unittest

from common.logger import get_logger


class TestGetLogger(unittest.TestCase):
    def test_returns_a_logger_with_the_requested_name(self):
        logger = get_logger("test_logger")
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "test_logger")

    def test_logs_messages(self):
        logger = get_logger("test_logger")
        with self.assertLogs("test_logger", level="INFO") as cm:
            logger.info("This is a test log message.")
        self.assertIn("This is a test log message.", cm.output[0])

    def test_same_name_returns_the_same_logger(self):
        # get_logger is a thin wrapper over logging.getLogger, which caches by name
        self.assertIs(get_logger("test_logger"), get_logger("test_logger"))

    def test_different_names_return_different_loggers(self):
        self.assertIsNot(get_logger("logger_a"), get_logger("logger_b"))


if __name__ == "__main__":
    unittest.main()
