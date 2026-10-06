import unittest
from unittest.mock import patch, AsyncMock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import main


class TestConfigValidation(unittest.TestCase):
    def test_validate_config_fails_when_variables_missing(self):
        """When mandatory env vars are missing, validate_config should exit with code 1."""
        with patch.object(config, "TELEGRAM_BOT_TOKEN", None), \
             patch.object(config, "TELEGRAM_CHAT_ID", None), \
             patch.object(config, "SUPABASE_URL", None), \
             patch.object(config, "SUPABASE_KEY", None):
            with self.assertRaises(SystemExit) as cm:
                config.validate_config(skip_in_tests=False)
            self.assertEqual(cm.exception.code, 1)

    def test_validate_config_succeeds_when_all_variables_present(self):
        """When all mandatory env vars are present, validate_config should not raise."""
        with patch.object(config, "TELEGRAM_BOT_TOKEN", "mock_token"), \
             patch.object(config, "TELEGRAM_CHAT_ID", "mock_chat"), \
             patch.object(config, "SUPABASE_URL", "https://mock.supabase.co"), \
             patch.object(config, "SUPABASE_KEY", "mock_key"):
            try:
                config.validate_config(skip_in_tests=False)
            except SystemExit:
                self.fail("validate_config raised SystemExit unexpectedly")


class TestSaveStateVersion(unittest.TestCase):
    def test_save_state_increments_version_only_once_across_retries(self):
        """Even if the first attempt fails and retries occur, _version must increment exactly once."""
        state = {"jobs": [], "_version": 5}
        
        attempt_count = 0
        async def mock_post(*args, **kwargs):
            nonlocal attempt_count
            attempt_count += 1
            mock_resp = AsyncMock()
            if attempt_count == 1:
                mock_resp.status_code = 500
                mock_resp.text = "Internal Server Error"
            else:
                mock_resp.status_code = 200
            return mock_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get.return_value.status_code = 404

        with patch("main.SUPABASE_URL", "https://mock.supabase.co"), \
             patch("main.SUPABASE_KEY", "mock_key"), \
             patch("main.httpx.AsyncClient") as mock_client_cls, \
             patch("asyncio.sleep", new=AsyncMock()):
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            import asyncio
            asyncio.run(main.save_state(state))

        self.assertEqual(state["_version"], 6, "Version should be incremented exactly once (from 5 to 6)")
        self.assertEqual(attempt_count, 2, "Should have retried and succeeded on attempt 2")


if __name__ == "__main__":
    unittest.main()
