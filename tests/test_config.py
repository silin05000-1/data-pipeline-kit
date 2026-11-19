import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pipeline.config import get_secret, load_config
from pipeline.errors import ConfigError
from pipeline.logging_utils import redact, register_secret


class ConfigTests(unittest.TestCase):
    def test_env_substitution_and_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text(json.dumps({
                "url": "${TEST_API_URL}",
                "name": "${TEST_MISSING:-fallback}",
            }), encoding="utf-8")
            with mock.patch.dict(os.environ, {"TEST_API_URL": "https://example.test"}):
                cfg = load_config(path)
            self.assertEqual(cfg["url"], "https://example.test")
            self.assertEqual(cfg["name"], "fallback")

    def test_missing_env_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cfg.json"
            path.write_text('{"url": "${DEFINITELY_UNSET_VAR}"}', encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_config(path)
            self.assertIn("DEFINITELY_UNSET_VAR", str(ctx.exception))

    def test_secret_is_redacted(self):
        with mock.patch.dict(os.environ, {"TEST_SECRET": "super-secret-value"}):
            value = get_secret("TEST_SECRET")
        self.assertEqual(value, "super-secret-value")
        self.assertEqual(redact("token=super-secret-value"), "token=***")

    def test_register_secret_ignores_short_values(self):
        register_secret("x")
        self.assertEqual(redact("value x"), "value x")


if __name__ == "__main__":
    unittest.main()
