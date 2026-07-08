"""FRED API calls with local CSV caching.

Usage as a library:
    df = get_series("GDP")                  # cached if available
    df = get_series("GDP", force_refresh=True)  # always re-pull

Usage as a CLI:
    python fetch.py --refresh                # refresh every series in config.SERIES
    python fetch.py --refresh --series GDP CPIAUCSL
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
    """Raised when FRED_API_KEY is not set in the environment."""


class FredRequestError(Exception):
    """Raised when a call to the FRED API fails (network error, bad key, bad response)."""


def _read_api_key() -> str:
    api_key = os.environ.get(config.FRED_API_KEY_ENV_VAR)
    if not api_key:
        raise MissingAPIKeyError(
            f"{config.FRED_API_KEY_ENV_VAR} is not set. Get a free key at "
            "https://fred.stlouisfed.org/docs/api/api_key.html, then export it "
            f"(export {config.FRED_API_KEY_ENV_VAR}=your_key_here) or add it to a .env file."
        )
    return api_key


def _cache_path(series_id: str):
    return config.DATA_DIR / f"{series_id}.csv"


def _fetch_from_api(series_id: str) -> pd.DataFrame:
    api_key = _read_api_key()
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


def get_series(series_id: str, force_refresh: bool = False) -> pd.DataFrame:
    cache_path = _cache_path(series_id)

    if not force_refresh and cache_path.exists():
        df = pd.read_csv(cache_path, parse_dates=["date"])
        return df

    df = _fetch_from_api(series_id)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path, index=False)
    return df


def get_multiple(series_ids, force_refresh: bool = False) -> dict:
    return {sid: get_series(sid, force_refresh=force_refresh) for sid in series_ids}


def _main():
    parser = argparse.ArgumentParser(description="Fetch and cache FRED series.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a re-pull from the FRED API instead of using the local cache.",
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
