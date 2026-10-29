import os
import tempfile
import unittest
import zipfile

from app import validate_config, test_llm_connection as check_llm_connection, pick_best_model, fetch_available_models
from core.downloader import ComponentDownloader
from core.generator import build_astrbot_config, build_napcat_config


class DownloaderTests(unittest.TestCase):
    def test_safe_extract_rejects_zip_slip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, "bad.zip")
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")
            extract_dir = os.path.join(temp_dir, "extract")
            with self.assertRaises(ValueError):
                ComponentDownloader._safe_extract_zip(zip_path, extract_dir)
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "escape.txt")))


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.user_config = {
            "master_qq": "12345678",
            "bot_qq": "87654321",
            "api_provider": "deepseek",
            "api_key": "sk-test",
            "api_base": "https://api.deepseek.com/v1",
            "model_name": "deepseek-chat",
            "napcat_port": 6199,
            "astrbot_port": 6185,
            "whitelist_only": True,
        }

    def test_astrbot_config_preserves_unrelated_settings(self):
        existing = {"log_level": "DEBUG", "provider": [{"id": "other"}]}
        config = build_astrbot_config(existing, self.user_config)

        self.assertEqual(config["log_level"], "DEBUG")
        self.assertEqual([item["id"] for item in config["provider"]], ["other", "baomiao-deepseek"])
        self.assertEqual(config["provider_settings"]["default_provider_id"], "baomiao-deepseek")
        self.assertEqual(config["admins_id"], ["12345678"])
        self.assertEqual(config["dashboard"]["host"], "127.0.0.1")
        self.assertEqual(config["platform"][0]["ws_reverse_port"], 6199)

    def test_napcat_reverse_ws_targets_astrbot_single_endpoint(self):
        config = build_napcat_config({"http": {"enable": False}}, self.user_config)
        self.assertFalse(config["ws"]["enable"])
        self.assertEqual(config["reverseWs"]["urls"], ["ws://127.0.0.1:6199/ws"])

    def test_baomiao_provider_is_supported(self):
        self.user_config["api_provider"] = "baomiao"
        config = build_astrbot_config({}, self.user_config)
        self.assertEqual(config["provider"][0]["provider"], "openai")
        self.assertEqual(config["provider"][0]["api_base"], "https://api.deepseek.com/v1")


class ValidationTests(unittest.TestCase):
    def test_config_validation(self):
        valid = {
            "master_qq": "12345678",
            "bot_qq": "87654321",
            "api_provider": "baomiao",
            "api_key": "sk-baomiao-test",
            "api_base": "https://open-ai.baomiao.cn/v1",
            "model_name": "deepseek-chat",
        }
        self.assertEqual(validate_config(valid, require_complete=True), "")
        invalid = dict(valid, master_qq="not-a-qq")
        self.assertIn("QQ", validate_config(invalid, require_complete=True))
        unsupported = dict(valid, api_provider="unknown_provider")
        self.assertIn("仅支持", validate_config(unsupported))

    def test_llm_connection_checks_key(self):
        ok, msg = check_llm_connection({"api_key": ""})
        self.assertFalse(ok)
        self.assertIn("有效", msg)

        ok, msg = check_llm_connection({"api_key": "bm-free-token"})
        self.assertFalse(ok)
        self.assertIn("有效", msg)


    def test_pick_best_model(self):
        models = [
            {"id": "deepseek-v4-pro", "name": "DeepSeek-V4-Pro"},
            {"id": "deepseek-flash", "name": "DeepSeek-V4.1-Flash"},
        ]
        self.assertEqual(pick_best_model(models), "deepseek-flash")
        self.assertEqual(pick_best_model(models, preferred="deepseek-v4-pro"), "deepseek-v4-pro")

    def test_fetch_available_models_fallback(self):
        models = fetch_available_models("", "")
        self.assertTrue(len(models) >= 1)
        self.assertEqual(models[0]["id"], "deepseek-flash")


if __name__ == "__main__":
    unittest.main()
