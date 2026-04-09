#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys

import requests

from src.yepbooking_availability import (
    MELBOURNE_TZ,
    Slot,
    list_available_slots,
    parse_input_date,
)


def _group_by_court(slots: list[Slot]) -> dict[int, list[Slot]]:
    grouped: dict[int, list[Slot]] = {court: [] for court in range(1, 9)}
    for slot in slots:
        grouped.setdefault(slot.court, []).append(slot)
    return grouped


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(
        description="List available badminton court slots (courts 1–8) for one date (Melbourne)."
    )
    parser.add_argument("date", help="Date: YYYY-MM-DD, DD-MM-YYYY, or DD/MM/YYYY")
    args = parser.parse_args()

    try:
        target_date = parse_input_date(args.date)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        slots = list_available_slots(target_date)
    except requests.RequestException as exc:
        print(f"Fetch failed: {exc}", file=sys.stderr)
        return 1

    print("Venue: ABC Abbotsford (Yep!Booking)")
    print(f"Date:  {target_date.isoformat()} (Australia/Melbourne)")
    print("Timezone: Australia/Melbourne")
    print()

    if not slots:
        print(
            "No available slots found for courts 1–8 on that day (or timetable empty)."
        )
        return 0

    grouped = _group_by_court(slots)
    for court in range(1, 9):
        print(f"Court {court}")
        court_slots = grouped.get(court, [])
        if not court_slots:
            print("  (none)")
            continue
        for slot in court_slots:
            mel_time = slot.start_utc.astimezone(MELBOURNE_TZ)
            print(
                f"  {slot.label}  "
                f"(Melbourne {mel_time.strftime('%Y-%m-%d %H:%M')}, lane id {slot.lane_id})"
            )
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
