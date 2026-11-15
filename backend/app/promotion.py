"""Moving guests up from the waitlist. Called after anything that frees spots:
a guest cancelling or shrinking their party, the host removing a guest, or
the host raising (or removing) the capacity.

The caller must already hold the event row lock (SELECT ... FOR UPDATE) in the
same transaction, so promotions can't race with new RSVPs.
"""
from psycopg import Connection

from app import repo
from app.rsvp_logic import to_promote


def promote_waitlist(conn: Connection, event_id: int, capacity: int | None) -> list[int]:
    attending = repo.attending_count(conn, event_id)
    waiting = [(row["id"], row["party_size"]) for row in repo.waitlist(conn, event_id)]
    promoted = to_promote(capacity, attending, waiting)
    repo.promote(conn, promoted)
    return promoted
