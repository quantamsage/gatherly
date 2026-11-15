"""Every SQL query in the app. All values are passed as parameters (%(name)s),
never formatted into the SQL string, so user input can't change a query."""

from psycopg import Connection
from psycopg.errors import UniqueViolation

# ---------- hosts ----------

def create_host(conn: Connection, email: str, password_hash: str) -> int | None:
    """Return the new host id, or None if the email is already registered."""
    try:
        with conn.transaction():  # savepoint, so a duplicate doesn't break the connection
            row = conn.execute(
                "INSERT INTO rsvp_hosts (email, password_hash) VALUES (%(email)s, %(hash)s) "
                "RETURNING id",
                {"email": email, "hash": password_hash},
            ).fetchone()
        return row["id"]
    except UniqueViolation:
        return None


def get_host_by_email(conn: Connection, email: str) -> dict | None:
    return conn.execute(
        "SELECT id, email, password_hash FROM rsvp_hosts WHERE email = %(email)s",
        {"email": email},
    ).fetchone()


def get_host_by_id(conn: Connection, host_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, email FROM rsvp_hosts WHERE id = %(id)s", {"id": host_id}
    ).fetchone()


# ---------- events ----------

# One event row plus its RSVP counts. "attending" adds up party sizes of confirmed
# yes RSVPs; waitlisted replies are counted separately and don't take a spot.
_EVENT_WITH_COUNTS = """
    SELECT e.id, e.host_id, e.slug, e.title, e.description, e.location,
           e.starts_at, e.capacity, e.rsvp_open, e.waitlist_enabled, e.created_at,
           COUNT(r.id) FILTER (WHERE r.response = 'yes' AND r.status = 'confirmed') AS yes,
           COUNT(r.id) FILTER (WHERE r.response = 'no')    AS no,
           COUNT(r.id) FILTER (WHERE r.response = 'maybe') AS maybe,
           COUNT(r.id) FILTER (WHERE r.status = 'waitlisted') AS waitlisted,
           COALESCE(SUM(r.party_size) FILTER (WHERE r.response = 'yes' AND r.status = 'confirmed'), 0)::int
               AS attending
    FROM rsvp_events e
    LEFT JOIN rsvp_responses r ON r.event_id = e.id
"""


def create_event(conn: Connection, host_id: int, slug: str, data: dict) -> int:
    row = conn.execute(
        """
        INSERT INTO rsvp_events
            (host_id, slug, title, description, location, starts_at, capacity, waitlist_enabled)
        VALUES (%(host_id)s, %(slug)s, %(title)s, %(description)s, %(location)s,
                %(starts_at)s, %(capacity)s, %(waitlist_enabled)s)
        RETURNING id
        """,
        {**data, "host_id": host_id, "slug": slug},
    ).fetchone()
    return row["id"]


def list_host_events(conn: Connection, host_id: int) -> list[dict]:
    return conn.execute(
        _EVENT_WITH_COUNTS + " WHERE e.host_id = %(host_id)s GROUP BY e.id ORDER BY e.starts_at",
        {"host_id": host_id},
    ).fetchall()


def get_host_event(conn: Connection, host_id: int, event_id: int) -> dict | None:
    """The event only if this host owns it. Ownership is part of the WHERE clause."""
    return conn.execute(
        _EVENT_WITH_COUNTS
        + " WHERE e.id = %(event_id)s AND e.host_id = %(host_id)s GROUP BY e.id",
        {"event_id": event_id, "host_id": host_id},
    ).fetchone()


def get_event_by_slug(conn: Connection, slug: str) -> dict | None:
    return conn.execute(
        _EVENT_WITH_COUNTS + " WHERE e.slug = %(slug)s GROUP BY e.id", {"slug": slug}
    ).fetchone()


def lock_host_event(conn: Connection, host_id: int, event_id: int) -> dict | None:
    """Lock this host's event row until the transaction ends (blocks concurrent RSVPs)."""
    return conn.execute(
        "SELECT id, capacity FROM rsvp_events WHERE id = %(event_id)s AND host_id = %(host_id)s FOR UPDATE",
        {"event_id": event_id, "host_id": host_id},
    ).fetchone()


def lock_event_by_slug(conn: Connection, slug: str) -> dict | None:
    """Lock the event row so two guests can't both take the last spot."""
    return conn.execute(
        "SELECT id, starts_at, capacity, rsvp_open, waitlist_enabled FROM rsvp_events "
        "WHERE slug = %(slug)s FOR UPDATE",
        {"slug": slug},
    ).fetchone()


def attending_count(conn: Connection, event_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(party_size), 0)::int AS attending FROM rsvp_responses "
        "WHERE event_id = %(event_id)s AND response = 'yes' AND status = 'confirmed'",
        {"event_id": event_id},
    ).fetchone()
    return row["attending"]


def update_event(conn: Connection, host_id: int, event_id: int, changes: dict) -> None:
    """Apply only the fields present in `changes`. The SQL text never changes:
    a missing field keeps its current value (COALESCE). capacity can be set
    to NULL on purpose, so it uses an explicit "set_capacity" flag instead."""
    conn.execute(
        """
        UPDATE rsvp_events SET
            title       = COALESCE(%(title)s, title),
            description = COALESCE(%(description)s, description),
            location    = COALESCE(%(location)s, location),
            starts_at   = COALESCE(%(starts_at)s, starts_at),
            rsvp_open   = COALESCE(%(rsvp_open)s, rsvp_open),
            waitlist_enabled = COALESCE(%(waitlist_enabled)s, waitlist_enabled),
            capacity    = CASE WHEN %(set_capacity)s THEN %(capacity)s ELSE capacity END
        WHERE id = %(event_id)s AND host_id = %(host_id)s
        """,
        {
            "title": changes.get("title"),
            "description": changes.get("description"),
            "location": changes.get("location"),
            "starts_at": changes.get("starts_at"),
            "rsvp_open": changes.get("rsvp_open"),
            "waitlist_enabled": changes.get("waitlist_enabled"),
            "set_capacity": "capacity" in changes,
            "capacity": changes.get("capacity"),
            "event_id": event_id,
            "host_id": host_id,
        },
    )


def delete_event(conn: Connection, host_id: int, event_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM rsvp_events WHERE id = %(event_id)s AND host_id = %(host_id)s",
        {"event_id": event_id, "host_id": host_id},
    )
    return cur.rowcount == 1


# ---------- responses ----------

# Waitlist position (1 = next in line) is computed, never stored, so it can't drift.
_RSVP_COLUMNS = """
    r.id, r.name, r.email, r.response, r.party_size, r.note, r.status, r.promoted_at, r.created_at,
    CASE WHEN r.status = 'waitlisted' THEN (
        SELECT count(*) FROM rsvp_responses w
        WHERE w.event_id = r.event_id AND w.status = 'waitlisted'
          AND (w.created_at, w.id) <= (r.created_at, r.id)
    ) END AS waitlist_position
"""


def list_rsvps(conn: Connection, event_id: int) -> list[dict]:
    return conn.execute(
        f"SELECT {_RSVP_COLUMNS} FROM rsvp_responses r WHERE r.event_id = %(event_id)s "
        "ORDER BY r.created_at DESC, r.id DESC",
        {"event_id": event_id},
    ).fetchall()


def create_rsvp(conn: Connection, event_id: int, data: dict) -> dict | None:
    """Return the new RSVP (with waitlist position), or None if this email already replied."""
    try:
        with conn.transaction():
            row = conn.execute(
                """
                INSERT INTO rsvp_responses
                    (event_id, name, email, response, party_size, note, status, manage_token_hash)
                VALUES (%(event_id)s, %(name)s, %(email)s, %(response)s, %(party_size)s, %(note)s,
                        %(status)s, %(manage_token_hash)s)
                RETURNING id
                """,
                {**data, "event_id": event_id},
            ).fetchone()
    except UniqueViolation:
        return None
    return get_rsvp(conn, row["id"])


def get_rsvp(conn: Connection, rsvp_id: int) -> dict | None:
    return conn.execute(
        f"SELECT {_RSVP_COLUMNS}, r.event_id FROM rsvp_responses r WHERE r.id = %(id)s", {"id": rsvp_id}
    ).fetchone()


def find_rsvp_by_token(conn: Connection, token_hash: str) -> dict | None:
    """The guest's own RSVP plus the event it belongs to (for the "manage" page)."""
    return conn.execute(
        f"""SELECT {_RSVP_COLUMNS}, r.event_id,
                   e.slug, e.title, e.location, e.starts_at
            FROM rsvp_responses r JOIN rsvp_events e ON e.id = r.event_id
            WHERE r.manage_token_hash = %(hash)s""",
        {"hash": token_hash},
    ).fetchone()


def lock_event_by_id(conn: Connection, event_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, capacity, starts_at FROM rsvp_events WHERE id = %(id)s FOR UPDATE", {"id": event_id}
    ).fetchone()


def set_party_size(conn: Connection, rsvp_id: int, party_size: int) -> None:
    conn.execute(
        "UPDATE rsvp_responses SET party_size = %(size)s WHERE id = %(id)s",
        {"id": rsvp_id, "size": party_size},
    )


def delete_rsvp(conn: Connection, event_id: int, rsvp_id: int) -> bool:
    cur = conn.execute(
        "DELETE FROM rsvp_responses WHERE id = %(id)s AND event_id = %(event_id)s",
        {"id": rsvp_id, "event_id": event_id},
    )
    return cur.rowcount == 1


def waitlist(conn: Connection, event_id: int) -> list[dict]:
    """Waitlisted RSVPs, oldest first."""
    return conn.execute(
        "SELECT id, party_size FROM rsvp_responses "
        "WHERE event_id = %(event_id)s AND status = 'waitlisted' ORDER BY created_at, id",
        {"event_id": event_id},
    ).fetchall()


def promote(conn: Connection, rsvp_ids: list[int]) -> None:
    if rsvp_ids:
        conn.execute(
            "UPDATE rsvp_responses SET status = 'confirmed', promoted_at = now() "
            "WHERE id = ANY(%(ids)s) AND status = 'waitlisted'",
            {"ids": rsvp_ids},
        )
