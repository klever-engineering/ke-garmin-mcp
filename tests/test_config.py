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
    def load(self, **env):
        base = {"GARMIN_ENV_FILE": str(Path(tempfile.mkdtemp()) / "missing.env"), **env}
        with mock.patch.dict(os.environ, base), mock.patch.object(config, "load_dotenv"):
            for key in ("GARMIN_TOKENS_DIR", "XDG_CONFIG_HOME"):
                if key not in env:
                    os.environ.pop(key, None)
            return config.load_settings()

    def test_default_token_dir_is_owner_config_dir_under_home(self):
        home = Path(tempfile.mkdtemp())
        with mock.patch.object(Path, "home", return_value=home):
            settings = self.load()
        self.assertEqual(home / ".config" / "lifeos" / "garmin-mcp" / "tokens", settings.garmin_tokens_dir)

    def test_xdg_config_home_moves_the_default(self):
        xdg = Path(tempfile.mkdtemp())
        self.assertEqual(xdg / "lifeos" / "garmin-mcp" / "tokens",
                         self.load(XDG_CONFIG_HOME=str(xdg)).garmin_tokens_dir)

    def test_explicit_token_dir_wins(self):
        target = Path(tempfile.mkdtemp()) / "tokens"
        self.assertEqual(target, self.load(GARMIN_TOKENS_DIR=str(target)).garmin_tokens_dir)

    def test_env_example_documents_the_code_default(self):
        example = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
        self.assertIn("# GARMIN_TOKENS_DIR=~/.config/lifeos/garmin-mcp/tokens", example)


class TokenPermissionTests(unittest.TestCase):
    def test_token_dir_and_files_become_owner_only(self):
        from garmin_mcp import client

        directory = Path(tempfile.mkdtemp()) / "tokens"
        directory.mkdir(mode=0o755)
        token = directory / "garmin_tokens.json"
        token.write_text("{}")
        token.chmod(0o644)
        client.secure_token_dir(directory)
        self.assertEqual(0o700, directory.stat().st_mode & 0o777)
        self.assertEqual(0o600, token.stat().st_mode & 0o777)

    def test_launch_scripts_do_not_load_env_or_token_defaults_themselves(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        for name in ("mcp_stdio.sh", "mcp_streamable_http.sh"):
            text = (scripts / name).read_text()
            with self.subTest(script=name):
                self.assertNotIn("source", text)
                self.assertNotIn("GARMIN_TOKENS_DIR=", text)


if __name__ == "__main__":
    unittest.main()
