"""Guest list CSV. Pure function, no database."""
import csv
import io

COLUMNS = ["name", "email", "response", "status", "party_size", "waitlist_position", "note", "replied_at"]
# Excel/Sheets run cells starting with these as formulas, so prefix them with '.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

# Coming first, then the waitlist in order, then maybe, then no.
_ORDER = {("yes", "confirmed"): 0, ("yes", "waitlisted"): 1, ("maybe", "confirmed"): 2, ("no", "confirmed"): 3}


def _safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def guest_list_csv(rows: list[dict]) -> str:
    ordered = sorted(
        rows,
        key=lambda r: (_ORDER[(r["response"], r["status"])], r["waitlist_position"] or 0, r["name"].lower()),
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    for r in ordered:
        writer.writerow([
            _safe(r["name"]), _safe(r["email"]), r["response"], r["status"], r["party_size"],
            r["waitlist_position"] or "", _safe(r["note"]), r["created_at"].isoformat(timespec="seconds"),
        ])
    return buffer.getvalue()
