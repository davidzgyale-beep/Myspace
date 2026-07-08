"""Run the fetch pipeline on a recurring interval using the `schedule` library.

For unattended/production use, a plain crontab entry (see crontab.example)
is usually more robust than a long-running foreground process -- this is
the lightweight option for interactive/dev use.
"""
from __future__ import annotations

import time

import schedule

from .config import DEFAULT_FETCH_INTERVAL_MINUTES
from .pipeline import run_fetch_cycle


def run_forever(interval_minutes: int = DEFAULT_FETCH_INTERVAL_MINUTES) -> None:
    print(f"[INFO] Scheduler started -- fetching every {interval_minutes} minute(s). Ctrl+C to stop.")
    run_fetch_cycle()  # run once immediately on startup, then on the schedule
    schedule.every(interval_minutes).minutes.do(run_fetch_cycle)
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Scheduler stopped by user.")
