"""Configuration is resolved in one place (config.py) for every entry point (#13)."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from garmin_mcp import config


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.project = self.tmp / "repositories" / "mcps" / "garmin-mcp"
        self.project.mkdir(parents=True)
        (self.tmp / ".env").write_text("GARMIN_USERNAME=workspace\n")

    def find_from(self, cwd: Path, **env):
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(Path, "cwd", return_value=cwd):
            os.environ.pop("GARMIN_ENV_FILE", None) if "GARMIN_ENV_FILE" not in env else None
            return config._find_env_file()

    def test_workspace_env_is_found_from_the_project_directory(self):
        self.assertEqual(self.tmp / ".env", self.find_from(self.project))

    def test_project_env_wins_over_workspace_env(self):
        (self.project / ".env").write_text("GARMIN_USERNAME=project\n")
        self.assertEqual(self.project / ".env", self.find_from(self.project))

    def test_explicit_env_file_wins_and_missing_explicit_file_loads_nothing(self):
        other = self.tmp / "other.env"
        other.write_text("X=1\n")
        self.assertEqual(other, self.find_from(self.project, GARMIN_ENV_FILE=str(other)))
        self.assertIsNone(self.find_from(self.project, GARMIN_ENV_FILE=str(self.tmp / "missing.env")))


class SettingsTests(unittest.TestCase):
    def test_default_token_dir_is_under_the_workspace_config_folder(self):
        env = {"GARMIN_ENV_FILE": "/nonexistent/.env"}
        with mock.patch.dict(os.environ, env), mock.patch.object(config, "load_dotenv"):
            os.environ.pop("GARMIN_TOKENS_DIR", None)
            settings = config.load_settings()
        root = config._workspace_root()
        self.assertTrue((root / "config").is_dir() and (root / "repositories").is_dir())
        self.assertEqual(root / "config" / "garmin-mcp" / "tokens", settings.garmin_tokens_dir)

    def test_env_example_matches_the_code_default(self):
        example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
        self.assertIn("GARMIN_TOKENS_DIR=config/garmin-mcp/tokens", example)

    def test_launch_scripts_do_not_load_env_or_token_defaults_themselves(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        for name in ("mcp_stdio.sh", "mcp_streamable_http.sh"):
            text = (scripts / name).read_text()
            with self.subTest(script=name):
                self.assertNotIn("source", text)
                self.assertNotIn("GARMIN_TOKENS_DIR=", text)


if __name__ == "__main__":
    unittest.main()
