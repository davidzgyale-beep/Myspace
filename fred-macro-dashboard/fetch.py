"""Multi-source data fetching (FRED + Alpha Vantage) with local CSV caching.

Usage as a library:
    df = get_series("GDP")                  # cached if available
    df = get_series("GDP", force_refresh=True)  # always re-pull

Usage as a CLI:
    python fetch.py --refresh                # refresh every series in config.SERIES
    python fetch.py --refresh --series GDP WTI
"""

import argparse
import os
import sys

import pandas as pd
import requests

import config

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


class MissingAPIKeyError(Exception):
    """Raised when a required API key is not set in the environment."""


class FredRequestError(Exception):
    """Raised when a call to a data source's API fails (network error, bad key, bad response)."""


def _read_api_key(env_var: str, signup_url: str) -> str:
    api_key = os.environ.get(env_var)
    if not api_key:
        raise MissingAPIKeyError(
            f"{env_var} is not set. Get a free key at {signup_url}, then export it "
            f"(export {env_var}=your_key_here) or add it to a .env file."
        )
    return api_key


def _cache_path(series_id: str):
    return config.DATA_DIR / f"{series_id}.csv"


def _fetch_from_fred(series_id: str) -> pd.DataFrame:
    api_key = _read_api_key(
        config.FRED_API_KEY_ENV_VAR,
        "https://fred.stlouisfed.org/docs/api/api_key.html",
    )
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
    }
    try:
        response = requests.get(config.FRED_BASE_URL, params=params, timeout=15)
    except requests.RequestException as exc:
        raise FredRequestError(
            f"Network error while fetching '{series_id}' from FRED: {exc}"
        ) from exc

    if response.status_code != 200:
        try:
            message = response.json().get("error_message", response.text)
        except ValueError:
            message = response.text
        raise FredRequestError(
            f"FRED API returned HTTP {response.status_code} for '{series_id}': {message}"
        )

    try:
        payload = response.json()
        observations = payload["observations"]
    except (ValueError, KeyError) as exc:
        raise FredRequestError(
            f"Unexpected response shape from FRED for '{series_id}': {exc}"
        ) from exc

    df = pd.DataFrame(observations)[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


def _fetch_from_alpha_vantage(series_id: str) -> pd.DataFrame:
    api_key = _read_api_key(
        config.ALPHA_VANTAGE_API_KEY_ENV_VAR,
        "https://www.alphavantage.co/support/#api-key",
    )
    params = {
        "function": series_id,
        "interval": "monthly",
        "apikey": api_key,
    }
    try:
        response = requests.get(config.ALPHA_VANTAGE_BASE_URL, params=params, timeout=15)
    except requests.RequestException as exc:
        raise FredRequestError(
            f"Network error while fetching '{series_id}' from Alpha Vantage: {exc}"
        ) from exc

    if response.status_code != 200:
        raise FredRequestError(
            f"Alpha Vantage returned HTTP {response.status_code} for '{series_id}': {response.text}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise FredRequestError(
            f"Unexpected response shape from Alpha Vantage for '{series_id}': {exc}"
        ) from exc

    # Alpha Vantage reports errors/rate limits with a 200 status and an
    # "Error Message"/"Note"/"Information" key instead of "data".
    if "data" not in payload:
        message = (
            payload.get("Error Message")
            or payload.get("Note")
            or payload.get("Information")
            or payload
        )
        raise FredRequestError(
            f"Alpha Vantage did not return data for '{series_id}': {message}"
        )

    df = pd.DataFrame(payload["data"])[["date", "value"]]
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


_FETCHERS = {
    "fred": _fetch_from_fred,
    "alpha_vantage": _fetch_from_alpha_vantage,
}


def get_series(series_id: str, force_refresh: bool = False) -> pd.DataFrame:
    cache_path = _cache_path(series_id)

    if not force_refresh and cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df

    source = config.SERIES[series_id]["source"]
    df = _FETCHERS[source](series_id)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    return df


def get_multiple(series_ids, force_refresh: bool = False) -> dict:
    return {sid: get_series(sid, force_refresh=force_refresh) for sid in series_ids}


def _main():
    parser = argparse.ArgumentParser(description="Fetch and cache macro/commodity series.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a re-pull from the source API instead of using the local cache.",
    )
    parser.add_argument(
        "--series",
        nargs="+",
        default=list(config.SERIES.keys()),
        help="Series IDs to fetch (default: all series configured in config.py).",
    )
    args = parser.parse_args()

    for series_id in args.series:
        try:
            df = get_series(series_id, force_refresh=args.refresh)
        except (MissingAPIKeyError, FredRequestError) as exc:
            print(f"[FAIL] {series_id}: {exc}", file=sys.stderr)
            continue
        latest = df.dropna(subset=["value"]).iloc[-1] if not df.empty else None
        latest_str = f"{latest['date'].date()} = {latest['value']}" if latest is not None else "no data"
        print(f"[OK]   {series_id}: {len(df)} observations cached, latest {latest_str}")


if __name__ == "__main__":
    _main()
