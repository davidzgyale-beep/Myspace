"""Thin HTTP client wrapper around SEC EDGAR / data.sec.gov endpoints.

Provides:
 - required User-Agent header injection
 - a token-bucket-style rate limiter (default 8 requests/second)
 - on-disk JSON caching keyed by URL
 - retry with exponential backoff for transient/5xx/429 errors
 - readable exceptions for 403 / 404 / 429 responses
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Union

import requests

logger = logging.getLogger(__name__)


class SECClientError(Exception):
    """Base exception for all SEC client errors."""


class SECNotFoundError(SECClientError):
    """Raised when SEC EDGAR returns HTTP 404 for a resource (e.g. unknown CIK)."""


class SECForbiddenError(SECClientError):
    """Raised when SEC EDGAR returns HTTP 403 (commonly a missing/invalid User-Agent)."""


class SECRateLimitError(SECClientError):
    """Raised when SEC EDGAR returns HTTP 429 and retries are exhausted."""


class SECRequestError(SECClientError):
    """Raised for other unexpected HTTP status codes or network failures."""


class RateLimiter:
    """Simple thread-safe rate limiter enforcing a minimum interval between calls."""

    def __init__(self, rate_per_second: float):
        self._min_interval = 1.0 / rate_per_second if rate_per_second > 0 else 0.0
        self._lock = Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            sleep_for = self._min_interval - elapsed
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last_call = time.monotonic()


class SECClient:
    def __init__(
        self,
        user_agent: str,
        cache_dir: Union[str, Path],
        rate_limit: float = 8.0,
        use_cache: bool = True,
        max_retries: int = 4,
        timeout: int = 30,
    ):
        if not user_agent or not user_agent.strip():
            raise SECClientError(
                "A non-empty SEC_USER_AGENT is required by SEC EDGAR for all requests."
            )
        self.headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip, deflate",
        }
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.use_cache = use_cache
        self.max_retries = max_retries
        self.timeout = timeout
        self._rate_limiter = RateLimiter(rate_limit)
        self._session = requests.Session()

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def get_json(self, url: str) -> dict:
        """GET a URL and return parsed JSON, using the on-disk cache when enabled."""
        cache_path = self._cache_path(url)
        if self.use_cache and cache_path.exists():
            logger.debug("Cache hit for %s", url)
            with cache_path.open("r", encoding="utf-8") as fh:
                return json.load(fh)

        data = self._request_with_retry(url)

        if self.use_cache:
            tmp_path = cache_path.with_suffix(".json.tmp")
            with tmp_path.open("w", encoding="utf-8") as fh:
                json.dump(data, fh)
            tmp_path.replace(cache_path)

        return data

    def _request_with_retry(self, url: str) -> dict:
        attempt = 0
        backoff = 1.0
        while True:
            attempt += 1
            self._rate_limiter.wait()
            try:
                response = self._session.get(url, headers=self.headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt > self.max_retries:
                    raise SECRequestError(f"Network error requesting {url}: {exc}") from exc
                logger.warning(
                    "Network error on attempt %d/%d for %s: %s", attempt, self.max_retries, url, exc
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            status = response.status_code

            if status == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SECRequestError(f"Invalid JSON returned from {url}: {exc}") from exc

            if status == 404:
                raise SECNotFoundError(
                    f"SEC EDGAR returned 404 Not Found for {url}. "
                    "The CIK/ticker may not exist or may have no data for this endpoint."
                )

            if status == 403:
                raise SECForbiddenError(
                    f"SEC EDGAR returned 403 Forbidden for {url}. "
                    "Check that SEC_USER_AGENT in your .env is a non-empty, descriptive "
                    "value as required by SEC (e.g. 'Company Name contact@example.com')."
                )

            if status == 429:
                if attempt > self.max_retries:
                    raise SECRateLimitError(
                        f"SEC EDGAR returned 429 Too Many Requests for {url} after "
                        f"{self.max_retries} retries. Lower EDGAR_RATE_LIMIT and try again."
                    )
                retry_after = response.headers.get("Retry-After")
                wait_time = float(retry_after) if retry_after else backoff
                logger.warning(
                    "429 rate limited on %s, retrying in %.1fs (attempt %d/%d)",
                    url,
                    wait_time,
                    attempt,
                    self.max_retries,
                )
                time.sleep(wait_time)
                backoff *= 2
                continue

            if 500 <= status < 600:
                if attempt > self.max_retries:
                    raise SECRequestError(
                        f"SEC EDGAR returned server error {status} for {url} after retries."
                    )
                logger.warning(
                    "Server error %d on %s, retrying in %.1fs (attempt %d/%d)",
                    status,
                    url,
                    backoff,
                    attempt,
                    self.max_retries,
                )
                time.sleep(backoff)
                backoff *= 2
                continue

            raise SECRequestError(
                f"Unexpected HTTP status {status} for {url}: {response.text[:200]!r}"
            )
