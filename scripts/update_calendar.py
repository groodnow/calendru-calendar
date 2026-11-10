#!/usr/bin/env python3
"""Fetch Calend.ru ICS, remove DTSTART/RDATE overlaps and duplicate UIDs."""
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
from icalendar import Calendar
import os
import sys

YEAR = datetime.now(ZoneInfo("Asia/Barnaul")).year
SOURCE_URL = os.environ.get(
    "CALENDRU_ICS_URL",
    f"https://www.calend.ru/ical/ical-russtate.ics?v=yy{YEAR}&b=1",
)
OUTPUT = Path("docs/calend-russtate.ics")


def stamp(event):
    """Prefer the most recently modified copy when a UID is repeated."""
    value = event.get("LAST-MODIFIED") or event.get("DTSTAMP")
    if value is None:
        return datetime.min
    value = value.dt
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    return value.replace(tzinfo=None)


def value_key(value):
    """Comparable key for DTSTART/RDATE values, retaining date vs datetime."""
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    return ("other", str(value))


def main():
    request = Request(SOURCE_URL, headers={"User-Agent": "Calendru-ICS-cleaner/1.0"})
    with urlopen(request, timeout=60) as response:
        raw = response.read()

    if not raw or b"BEGIN:VCALENDAR" not in raw:
        raise RuntimeError("Downloaded content is empty or is not an iCalendar file")

    calendar = Calendar.from_ical(raw)
    if calendar.name != "VCALENDAR":
        raise RuntimeError("Downloaded file did not parse as VCALENDAR")

    events = list(calendar.walk("VEVENT"))
    if not events:
        raise RuntimeError("No VEVENT records found; refusing to publish an empty calendar")

    # Remove only RDATE values that duplicate this event's DTSTART.
    recurrence_overlaps = 0
    for event in events:
        start = event.get("DTSTART")
        if start is None:
            continue
        start_key = value_key(start.dt)
        rdate_properties = list(event.getall("RDATE"))
        if not rdate_properties:
            continue

        filtered_properties = []
        changed = False
        for prop in rdate_properties:
            kept = [item for item in prop.dts if value_key(item.dt) != start_key]
            recurrence_overlaps += len(prop.dts) - len(kept)
            changed = changed or len(kept) != len(prop.dts)
            if kept:
                filtered_properties.append((prop, kept)

        if changed:
            event.pop("RDATE")
            for original, kept in filtered_properties:
                from icalendar import vDDDLists
                replacement = vDDDLists(kept)
                event.add("RDATE", replacement, encode=0)

    # RFC 5545 UID identifies one logical event. Keep the latest modified copy.
    by_uid = {}
    no_uid = []
    for event in events:
        uid = str(event.get("UID", "")).strip()
        if not uid:
            no_uid.append(event)
            continue
        current = by_uid.get(uid)
        if current is None or stamp(event) >= stamp(current):
            by_uid[uid] = event

    unique_events = list(by_uid.values()) + no_uid
    duplicate_uids_removed = len(events) - len(unique_events)

    # Retain calendar-level properties and any non-event components.
    output = Calendar()
    for key, value in calendar.items():
        output.add(key, value)
    for component in calendar.subcomponents:
        if component.name != "VEVENT":
            output.add_component(component)
    for event in unique_events:
        output.add_component(event)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    data = output.to_ical()
    if b"BEGIN:VCALENDAR" not in data or b"END:VCALENDAR" not in data:
        raise RuntimeError("Output validation failed")
    OUTPUT.write_bytes(data)

    print(f"Source events: {len(events)}")
    print(f"DTSTART/RDATE overlaps removed: {recurrence_overlaps}")
    print(f"Duplicate UIDs removed: {duplicate_uids_removed}")
    print(f"Published events: {len(unique_events)}")
    print(f"Source URL: {SOURCE_URL}")
    print(f"Output: {OUTPUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
