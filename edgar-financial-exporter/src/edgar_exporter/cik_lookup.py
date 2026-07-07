"""Ticker <-> CIK resolution using SEC's public company_tickers.json list."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from .sec_client import SECClient

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


class TickerNotFoundError(Exception):
    """Raised when a ticker symbol cannot be resolved to a CIK."""


class InvalidCIKError(Exception):
    """Raised when a supplied CIK string is not a valid SEC CIK."""


def normalize_cik(raw_cik: str) -> str:
    """Normalize a CIK to SEC's canonical 10-digit, zero-padded string form.

    Accepts plain digits ("320193"), an optional "CIK" prefix ("CIK0000320193"),
    and already zero-padded values.
    """
    cik = str(raw_cik).strip().upper()
    if cik.startswith("CIK"):
        cik = cik[3:]

    if not cik.isdigit():
        raise InvalidCIKError(f"'{raw_cik}' is not a valid CIK: it must contain only digits.")

    if len(cik) > 10:
        raise InvalidCIKError(f"'{raw_cik}' is not a valid CIK: too many digits (max 10).")

    value = int(cik)
    if value <= 0:
        raise InvalidCIKError(f"'{raw_cik}' is not a valid CIK: must be a positive number.")

    return cik.zfill(10)


def is_probably_cik(token: str) -> bool:
    """Heuristic: a token is treated as a CIK if it is numeric (with optional CIK prefix)."""
    stripped = token.strip().upper()
    if stripped.startswith("CIK"):
        stripped = stripped[3:]
    return stripped.isdigit()


class CIKLookup:
    """Resolves tickers to CIKs using SEC's company_tickers.json, lazily loaded/cached."""

    def __init__(self, client: SECClient):
        self._client = client
        self._ticker_map: Optional[dict] = None

    def _load(self) -> None:
        if self._ticker_map is not None:
            return
        raw = self._client.get_json(TICKERS_URL)
        mapping = {}
        for entry in raw.values():
            ticker = str(entry["ticker"]).upper()
            mapping[ticker] = {
                "cik": str(entry["cik_str"]).zfill(10),
                "title": entry.get("title"),
            }
        self._ticker_map = mapping

    def ticker_to_cik(self, ticker: str) -> str:
        self._load()
        info = self._ticker_map.get(ticker.strip().upper())
        if info is None:
            raise TickerNotFoundError(
                f"Ticker '{ticker}' was not found in SEC's company_tickers.json list. "
                "Double-check the symbol, or pass a CIK directly instead."
            )
        return info["cik"]

    def company_title(self, ticker: str) -> Optional[str]:
        self._load()
        info = self._ticker_map.get(ticker.strip().upper())
        return info["title"] if info else None

    def resolve(self, ticker_or_cik: str) -> Tuple[str, Optional[str]]:
        """Resolve a user-supplied ticker or CIK to a (cik10, company_title_or_None) tuple."""
        token = ticker_or_cik.strip()
        if is_probably_cik(token):
            return normalize_cik(token), None
        cik10 = self.ticker_to_cik(token)
        title = self.company_title(token)
        return cik10, title
