import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route_bot.config import load_local_env


class ConfigTests(unittest.TestCase):
    def test_env_file_loads_and_keeps_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("# comment\nTELEGRAM_BOT_TOKEN=from-file\nALLOW_PLACEHOLDERS='1'\n", encoding="utf-8")
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "from-host"}, clear=True):
                load_local_env(path)
                self.assertEqual(os.environ["TELEGRAM_BOT_TOKEN"], "from-host")
                self.assertEqual(os.environ["ALLOW_PLACEHOLDERS"], "1")


if __name__ == "__main__":
    unittest.main()
