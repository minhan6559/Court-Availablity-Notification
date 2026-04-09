from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://abbotsford-badminton-club.yepbooking.com.au"
SCHEMA_URL = f"{BASE_URL}/ajax/ajax.schema.php"

# Internal lane row ids in HTML -> court numbers 1–8.
LANE_TO_COURT: dict[str, int] = {
    "1": 1,
    "2": 2,
    "68": 3,
    "69": 4,
    "70": 5,
    "73": 6,
    "74": 7,
    "75": 8,
}

MELBOURNE_TZ = ZoneInfo("Australia/Melbourne")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

REL_RE = re.compile(r"^cell\|(?P<sport>\d+)\|(?P<lane>\d+)\|(?P<ts>\d+)\|")


@dataclass(frozen=True)
class Slot:
    court: int
    lane_id: str
    start_utc: datetime
    label: str


def parse_input_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(
        f"Unrecognised date {value!r}; use YYYY-MM-DD, DD-MM-YYYY, or DD/MM/YYYY"
    )


def _rel_string(anchor: Tag) -> str | None:
    raw = anchor.get("rel")
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list) and raw:
        return raw[0]
    return None


def fetch_schema_html(
    target_date: date,
    *,
    sport_id: int = 1,
    timetable_width: int = 1200,
    base_url: str = BASE_URL,
    timeout_seconds: int = 60,
) -> str:
    params = {
        "day": target_date.day,
        "month": target_date.month,
        "year": target_date.year,
        "id_sport": sport_id,
        "default_view": "week",
        "reset_date": 0,
        "event": "changeWeek",
        "id_infotab": 0,
        "time": "",
        "filterId": "false",
        "filterChecked": 0,
        "tab_type": "normal",
        "display_type": "timetable",
        "labels": "",
        "timetableWidth": timetable_width,
        "schema_fixed_date": "",
    }
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": f"{base_url}/",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
    }

    response = requests.get(SCHEMA_URL, params=params, headers=headers, timeout=timeout_seconds)
    response.raise_for_status()
    if response.status_code != 200:
        raise RuntimeError(f"Unexpected HTTP status: {response.status_code}")
    return response.text


def parse_available_slots_from_html(
    html: str,
    target_date: date,
    *,
    tz: ZoneInfo = MELBOURNE_TZ,
    lane_to_court: dict[str, int] = LANE_TO_COURT,
) -> list[Slot]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set[tuple[str, int]] = set()
    slots: list[Slot] = []

    for anchor in soup.find_all("a"):
        classes = anchor.get("class") or []
        if "empty" not in classes:
            continue

        aria = (anchor.get("aria-label") or "").strip()
        if "Available" not in aria:
            continue

        rel_value = _rel_string(anchor)
        if not rel_value:
            continue

        match = REL_RE.match(rel_value)
        if not match:
            continue

        lane_id = match.group("lane")
        timestamp_utc = int(match.group("ts"))
        start_utc = datetime.fromtimestamp(timestamp_utc, tz=timezone.utc)
        start_local = start_utc.astimezone(tz)

        if start_local.date() != target_date:
            continue

        court = lane_to_court.get(lane_id)
        if court is None:
            continue

        dedupe_key = (lane_id, timestamp_utc)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        label = aria.replace(" - Available", "").strip()
        slots.append(Slot(court=court, lane_id=lane_id, start_utc=start_utc, label=label))

    slots.sort(key=lambda s: (s.court, s.start_utc))
    return slots


def list_available_slots(target_date: date) -> list[Slot]:
    html = fetch_schema_html(target_date)
    return parse_available_slots_from_html(html, target_date)
