#!/usr/bin/env python3
from __future__ import annotations

import os
import smtplib
import sys
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from src.yepbooking_availability import (
    MELBOURNE_TZ,
    Slot,
    list_available_slots,
    parse_input_date,
)

SLOT_DURATION = timedelta(minutes=30)

# A chain is a tuple of (court, start_local_datetime) per 30-min block.
Chain = tuple[tuple[int, datetime], ...]


def _parse_time(value: str, tz: ZoneInfo, ref_date: date) -> datetime:
    """Parse HH:MM into a timezone-aware datetime on ref_date."""
    h, m = value.strip().split(":")
    return datetime(
        ref_date.year, ref_date.month, ref_date.day, int(h), int(m), tzinfo=tz
    )


def _adjacency_score(chain: Chain) -> int:
    """Lower score = courts are more numerically adjacent."""
    courts = [c for c, _ in chain]
    return sum(abs(courts[i + 1] - courts[i]) for i in range(len(courts) - 1))


def _is_single_court(chain: Chain) -> bool:
    return len({c for c, _ in chain}) == 1


def _chain_priority(chain: Chain) -> tuple[int, int, int]:
    """Lower tuple = higher priority. Used for sorting and group winner selection."""
    single = 0 if _is_single_court(chain) else 1
    score = _adjacency_score(chain)
    min_court = min(c for c, _ in chain)
    return (single, score, min_court)


def _format_chain(chain: Chain) -> str:
    if _is_single_court(chain):
        court = chain[0][0]
        start = chain[0][1]
        end = chain[-1][1] + SLOT_DURATION
        return f"Court {court}: {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"

    parts: list[str] = []
    # Merge consecutive blocks on the same court into one segment
    seg_court, seg_start = chain[0]
    seg_end = chain[0][1] + SLOT_DURATION
    for court, t in chain[1:]:
        block_end = t + SLOT_DURATION
        if court == seg_court and t == seg_end:
            seg_end = block_end
        else:
            parts.append(
                f"Court {seg_court} ({seg_start.strftime('%H:%M')}–{seg_end.strftime('%H:%M')})"
            )
            seg_court, seg_start, seg_end = court, t, block_end
    parts.append(
        f"Court {seg_court} ({seg_start.strftime('%H:%M')}–{seg_end.strftime('%H:%M')})"
    )
    return " + ".join(parts)


def find_suggestions(
    slots: list[Slot],
    session_hours: float,
    window_start: datetime,
    window_end: datetime,
) -> list[Chain]:
    """
    Return the best chain suggestion per (start_time, first_court) pair.

    Algorithm:
    1. Filter slots to the requested time window.
    2. Index available (court, start_time) pairs for O(1) lookup.
    3. DFS over every possible chain_start, enumerating all valid chains.
    4. Group chains by (chain_start, first_court); keep only the highest-priority
       chain in each group.
    5. Sort and return.
    """
    n_blocks = round(session_hours / 0.5)  # number of 30-min blocks needed

    # Step 1 & 2: filter and index
    available: set[tuple[int, datetime]] = set()
    for slot in slots:
        local = slot.start_utc.astimezone(MELBOURNE_TZ)
        block_end = local + SLOT_DURATION
        if local >= window_start and block_end <= window_end:
            available.add((slot.court, local))

    if not available:
        return []

    # Collect all distinct start times within the window where a chain could begin
    min_start = window_start
    max_start = window_end - timedelta(hours=session_hours)

    # Step 3: DFS chain enumeration
    # For each chain_start, enumerate all valid chains via DFS
    # best[(chain_start, first_court)] = highest-priority chain found so far
    best: dict[tuple[datetime, int], Chain] = {}

    t0 = min_start
    while t0 <= max_start:
        times = [t0 + SLOT_DURATION * i for i in range(n_blocks)]

        # Collect courts available at each time step; prune early if any step is empty
        courts_at: list[list[int]] = []
        pruned = False
        for t in times:
            available_courts = sorted(c for c in range(1, 9) if (c, t) in available)
            if not available_courts:
                pruned = True
                break
            courts_at.append(available_courts)

        if not pruned:
            # DFS: stack holds (depth, partial_chain)
            stack: list[tuple[int, list[tuple[int, datetime]]]] = [(0, [])]
            while stack:
                depth, partial = stack.pop()
                if depth == n_blocks:
                    chain: Chain = tuple(partial)
                    key = (t0, chain[0][0])
                    if key not in best or _chain_priority(chain) < _chain_priority(
                        best[key]
                    ):
                        best[key] = chain
                    continue
                t = times[depth]
                for court in courts_at[depth]:
                    stack.append((depth + 1, partial + [(court, t)]))

        t0 += SLOT_DURATION

    # Step 5: collect winners, sort for output
    winners = list(best.values())
    winners.sort(key=lambda c: (_chain_priority(c), c[0][1]))
    return winners


def _send_email(smtp_host: str, smtp_port: int, smtp_user: str, smtp_password: str,
                to: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, [to], msg.as_string())
    print(f"Email sent to {to}.")


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    load_dotenv()

    # Read config from environment
    dates_raw = os.getenv("DATES", "").strip()
    session_raw = os.getenv("SESSION_LENGTH_HOURS", "").strip()
    window_start_raw = os.getenv("WINDOW_START", "").strip()
    window_end_raw = os.getenv("WINDOW_END", "").strip()

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port_raw = os.getenv("SMTP_PORT", "587").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    email_to = os.getenv("EMAIL_TO", "").strip()
    email_subject = os.getenv("EMAIL_SUBJECT", "Court Availability Suggestions").strip()

    send_email = bool(smtp_host and smtp_user and smtp_password and email_to)

    missing = [
        name
        for name, val in [
            ("DATES", dates_raw),
            ("SESSION_LENGTH_HOURS", session_raw),
            ("WINDOW_START", window_start_raw),
            ("WINDOW_END", window_end_raw),
        ]
        if not val
    ]
    if missing:
        print(f"Missing .env variables: {', '.join(missing)}", file=sys.stderr)
        print("See .env.example for the required format.", file=sys.stderr)
        return 2

    try:
        session_hours = float(session_raw)
        if session_hours <= 0:
            raise ValueError
    except ValueError:
        print(
            "SESSION_LENGTH_HOURS must be a positive number (e.g. 2 or 1.5).",
            file=sys.stderr,
        )
        return 2

    date_strings = [d.strip() for d in dates_raw.split(",") if d.strip()]
    parsed_dates: list[date] = []
    for ds in date_strings:
        try:
            parsed_dates.append(parse_input_date(ds))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    exit_code = 0
    email_lines: list[str] = []
    any_suggestions = False

    for target_date in parsed_dates:
        window_start = _parse_time(window_start_raw, MELBOURNE_TZ, target_date)
        window_end = _parse_time(window_end_raw, MELBOURNE_TZ, target_date)

        if window_start >= window_end:
            print(
                f"WINDOW_START must be before WINDOW_END for {target_date}.",
                file=sys.stderr,
            )
            exit_code = 2
            continue

        if (window_end - window_start).total_seconds() / 3600 < session_hours:
            print(
                f"Time window {window_start_raw}–{window_end_raw} is shorter than "
                f"session length {session_hours}h for {target_date}.",
                file=sys.stderr,
            )
            exit_code = 2
            continue

        header = (
            f"Date: {target_date.strftime('%d/%m/%Y')} — {session_hours:g}h session, "
            f"window {window_start_raw}–{window_end_raw} (Melbourne)"
        )
        print(header)
        email_lines.append(header)

        try:
            slots = list_available_slots(target_date)
        except requests.RequestException as exc:
            msg = f"  Fetch failed: {exc}"
            print(msg, file=sys.stderr)
            email_lines.append(msg)
            exit_code = 1
            continue

        suggestions = find_suggestions(slots, session_hours, window_start, window_end)

        if not suggestions:
            print("  No suggestions found.")
            email_lines.append("  No suggestions found.")
        else:
            any_suggestions = True
            for chain in suggestions:
                line = f"  {_format_chain(chain)}"
                print(line)
                email_lines.append(line)

        print()
        email_lines.append("")

    if send_email and email_lines and any_suggestions:
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            print(f"Invalid SMTP_PORT value: {smtp_port_raw!r}", file=sys.stderr)
            return 2
        date_labels = ", ".join(d.strftime("%d/%m/%Y") for d in parsed_dates)
        full_subject = f"{email_subject} — {date_labels}"
        try:
            _send_email(smtp_host, smtp_port, smtp_user, smtp_password,
                        email_to, full_subject, "\n".join(email_lines))
        except Exception as exc:
            print(f"Email send failed: {exc}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
