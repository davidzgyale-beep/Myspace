"""Application configuration loaded from environment variables / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv

DEFAULT_CACHE_DIR = "data/cache"
DEFAULT_RATE_LIMIT = 8.0


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass
class Config:
    user_agent: str
    base_url: str = "https://data.sec.gov"
    www_url: str = "https://www.sec.gov"
    cache_dir: Path = Path(DEFAULT_CACHE_DIR)
    rate_limit: float = DEFAULT_RATE_LIMIT
    request_timeout: int = 30


def load_config(env_path: Optional[Union[str, Path]] = None) -> Config:
    """Load configuration from the environment (and a .env file if present).

    Raises:
        ConfigError: if SEC_USER_AGENT is missing/blank.
    """
    load_dotenv(dotenv_path=env_path)

    user_agent = os.getenv("SEC_USER_AGENT", "").strip()
    if not user_agent:
        raise ConfigError(
            "SEC_USER_AGENT is not set. SEC EDGAR requires a descriptive User-Agent "
            "header on every request (e.g. 'Your Name your.email@example.com'). "
            "Copy .env.example to .env and set SEC_USER_AGENT before running again."
        )

    cache_dir = Path(os.getenv("EDGAR_CACHE_DIR", DEFAULT_CACHE_DIR))
    try:
        rate_limit = float(os.getenv("EDGAR_RATE_LIMIT", str(DEFAULT_RATE_LIMIT)))
    except ValueError as exc:
        raise ConfigError(
            f"EDGAR_RATE_LIMIT must be a number, got '{os.getenv('EDGAR_RATE_LIMIT')}'"
        ) from exc

    if rate_limit <= 0:
        raise ConfigError("EDGAR_RATE_LIMIT must be greater than 0.")

    cache_dir.mkdir(parents=True, exist_ok=True)

    return Config(user_agent=user_agent, cache_dir=cache_dir, rate_limit=rate_limit)
