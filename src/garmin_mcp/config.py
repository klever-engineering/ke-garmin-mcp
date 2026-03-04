from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _find_env_file() -> Path | None:
    explicit_env_file = os.getenv("GARMIN_ENV_FILE")
    if explicit_env_file:
        candidate = Path(explicit_env_file).expanduser()
        if candidate.exists():
            return candidate
        return None

    current = Path.cwd().resolve()
    for candidate_dir in [current, *current.parents]:
        env_file = candidate_dir / ".env"
        if env_file.exists():
            return env_file
    return None


def load_runtime_env() -> None:
    env_file = _find_env_file()
    if env_file is not None:
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(override=False)


@dataclass(slots=True)
class Settings:
    garmin_username: str | None
    garmin_password: str | None
    garmin_tokens_dir: Path
    max_range_days: int


def load_settings() -> Settings:
    load_runtime_env()
    tokens_dir = Path(os.getenv("GARMIN_TOKENS_DIR", ".state/garmin-tokens"))
    max_range_days = int(os.getenv("GARMIN_MAX_RANGE_DAYS", "93"))
    return Settings(
        garmin_username=os.getenv("GARMIN_USERNAME"),
        garmin_password=os.getenv("GARMIN_PASSWORD"),
        garmin_tokens_dir=tokens_dir,
        max_range_days=max_range_days,
    )

