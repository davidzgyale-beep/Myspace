import pytest

from edgar_exporter.cik_lookup import (
    CIKLookup,
    InvalidCIKError,
    TickerNotFoundError,
    normalize_cik,
)


def test_normalize_cik_pads_to_ten_digits():
    assert normalize_cik("320193") == "0000320193"


def test_normalize_cik_accepts_cik_prefix():
    assert normalize_cik("CIK0000320193") == "0000320193"


def test_normalize_cik_already_padded_is_idempotent():
    assert normalize_cik("0000320193") == "0000320193"


def test_normalize_cik_rejects_non_numeric():
    with pytest.raises(InvalidCIKError):
        normalize_cik("ABC123")


def test_normalize_cik_rejects_too_long():
    with pytest.raises(InvalidCIKError):
        normalize_cik("12345678901")


def test_normalize_cik_rejects_zero():
    with pytest.raises(InvalidCIKError):
        normalize_cik("0")


class _FakeClient:
    """Stands in for SECClient so lookup tests don't hit the network."""

    def __init__(self, payload):
        self._payload = payload

    def get_json(self, url):
        return self._payload


SAMPLE_TICKERS = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
}


def test_ticker_to_cik_found():
    lookup = CIKLookup(_FakeClient(SAMPLE_TICKERS))
    assert lookup.ticker_to_cik("aapl") == "0000320193"


def test_ticker_to_cik_not_found():
    lookup = CIKLookup(_FakeClient(SAMPLE_TICKERS))
    with pytest.raises(TickerNotFoundError):
        lookup.ticker_to_cik("ZZZZ")


def test_resolve_detects_cik_vs_ticker():
    lookup = CIKLookup(_FakeClient(SAMPLE_TICKERS))

    cik, title = lookup.resolve("0000320193")
    assert cik == "0000320193"
    assert title is None

    cik2, title2 = lookup.resolve("MSFT")
    assert cik2 == "0000789019"
    assert title2 == "MICROSOFT CORP"
