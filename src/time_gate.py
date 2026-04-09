#!/usr/bin/env python3
from __future__ import annotations

import os
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv


def _get_env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _write_github_output(key: str, value: str) -> None:
    """
    Write a step output for GitHub Actions.
    See: https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-an-output-parameter
    """
    path = os.getenv("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{key}={value}\n")


def main() -> int:
    load_dotenv()
    run_tz = _get_env("RUN_TZ", "Australia/Melbourne")
    run_days_raw = _get_env("RUN_DAYS", "thu,fri").lower()
    start_hour_raw = _get_env("RUN_START_HOUR", "8")
    end_hour_raw = _get_env("RUN_END_HOUR", "12")

    try:
        start_hour = int(start_hour_raw)
        end_hour = int(end_hour_raw)
    except ValueError:
        print(
            f"Invalid RUN_START_HOUR/RUN_END_HOUR: {start_hour_raw!r}/{end_hour_raw!r}"
        )
        _write_github_output("continue", "false")
        return 1

    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23 and start_hour <= end_hour):
        print(
            f"Invalid hour window: {start_hour}..{end_hour} (must be 0..23, start<=end)"
        )
        _write_github_output("continue", "false")
        return 1

    day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    wanted_days: set[int] = set()
    for part in [p.strip() for p in run_days_raw.split(",") if p.strip()]:
        if part in day_map:
            wanted_days.add(day_map[part])
        else:
            print(f"Invalid RUN_DAYS entry: {part!r}. Use like: thu,fri")
            _write_github_output("continue", "false")
            return 1

    tz = ZoneInfo(run_tz)
    now = datetime.now(tz)

    is_wanted_day = now.weekday() in wanted_days
    in_window = (now.hour >= start_hour) and (now.hour <= end_hour)  # inclusive
    should_continue = is_wanted_day and in_window

    print(f"Local now ({run_tz}): {now.isoformat(timespec='minutes')}")
    print(
        f"Window: days={sorted(wanted_days)} hours={start_hour}..{end_hour} (inclusive)"
    )
    print(f"Decision: {'continue' if should_continue else 'skip'}")

    _write_github_output("continue", "true" if should_continue else "false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
