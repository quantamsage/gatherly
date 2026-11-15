"""Build an iCalendar (.ics, RFC 5545) file for one event. No dependencies."""
from datetime import datetime, timedelta, timezone

# Events only have a start time, so calendars get a 2-hour block.
DEFAULT_DURATION = timedelta(hours=2)


def _escape(text: str) -> str:
    """Escape text values: backslash, semicolon, comma and newlines."""
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line: str) -> str:
    """Lines longer than 75 octets are folded with CRLF + space."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        piece = char.encode("utf-8")
        if len(current) + len(piece) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += piece
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_ics(event: dict, now: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gatherly//RSVP//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event['slug']}@gatherly",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(event['starts_at'])}",
        f"DTEND:{_utc(event['starts_at'] + DEFAULT_DURATION)}",
        f"SUMMARY:{_escape(event['title'])}",
    ]
    if event["location"]:
        lines.append(f"LOCATION:{_escape(event['location'])}")
    if event["description"]:
        lines.append(f"DESCRIPTION:{_escape(event['description'])}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
