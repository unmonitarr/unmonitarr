import logging
import unittest
from unittest.mock import patch

from common import logging_setup


class TestLoggingSetup(unittest.TestCase):
    """setup_logging() takes no arguments - it reads the level from Config.LOG_LEVEL."""

    def test_configures_root_logger_with_config_level(self):
        with patch.object(logging_setup.Config, "LOG_LEVEL", "DEBUG"), \
             patch.object(logging_setup.logging, "basicConfig") as mock_basic_config:
            logging_setup.setup_logging()

        mock_basic_config.assert_called_once()
        kwargs = mock_basic_config.call_args.kwargs
        self.assertEqual(kwargs["level"], "DEBUG")
        self.assertIn("%(levelname)s", kwargs["format"])
        self.assertIn("%(name)s", kwargs["format"])
        self.assertIn("%(message)s", kwargs["format"])

    def test_passes_through_configured_level(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR"):
            with patch.object(logging_setup.Config, "LOG_LEVEL", level), \
                 patch.object(logging_setup.logging, "basicConfig") as mock_basic_config:
                logging_setup.setup_logging()
            self.assertEqual(mock_basic_config.call_args.kwargs["level"], level)

    def test_takes_no_arguments(self):
        with patch.object(logging_setup.logging, "basicConfig"):
            with self.assertRaises(TypeError):
                logging_setup.setup_logging(logging.DEBUG)


if __name__ == "__main__":
    unittest.main()
