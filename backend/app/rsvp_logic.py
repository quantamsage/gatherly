"""Business rules for RSVPs. Pure functions (no database, no web), so they are
easy to unit test. The routes call these; the frontend never re-implements them."""

from datetime import datetime


def spots_left(capacity: int | None, attending: int) -> int | None:
    """People who can still say yes. None means unlimited."""
    if capacity is None:
        return None
    return max(capacity - attending, 0)


def is_accepting_rsvps(
    rsvp_open: bool,
    starts_at: datetime,
    capacity: int | None,
    attending: int,
    now: datetime,
    waitlist_enabled: bool = False,
) -> bool:
    """Open for RSVPs only if the host left it open, it hasn't started, and it
    isn't full (a full event with a waitlist still takes replies)."""
    if not rsvp_open or starts_at <= now:
        return False
    return waitlist_enabled or spots_left(capacity, attending) != 0


def rsvp_rejection(
    *,
    rsvp_open: bool,
    starts_at: datetime,
    capacity: int | None,
    attending: int,
    response: str,
    party_size: int,
    now: datetime,
    waitlist_enabled: bool = False,
) -> tuple[str, str] | None:
    """Return (error_code, message) if this RSVP must be refused, else None.

    "No" and "maybe" answers are always allowed while RSVPs are open: they
    don't take a spot. A "yes" must fit in the spots left, unless the event
    has a waitlist, in which case it is accepted onto the waitlist (see
    rsvp_status). A party bigger than the whole event is refused either way.
    """
    if not rsvp_open or starts_at <= now:
        return ("RSVP_CLOSED", "RSVPs for this event are closed.")
    if response == "yes":
        if capacity is not None and party_size > capacity:
            return ("EVENT_FULL", f"This event only has room for {capacity}. Reduce your party size.")
        left = spots_left(capacity, attending)
        if left is not None and party_size > left and not waitlist_enabled:
            if left == 0:
                return ("EVENT_FULL", "This event is full.")
            return ("EVENT_FULL", f"Only {left} spot(s) left. Reduce your party size.")
    return None


def rsvp_status(capacity: int | None, attending: int, response: str, party_size: int) -> str:
    """For an RSVP that wasn't rejected: does it take a spot now, or join the waitlist?"""
    if response != "yes":
        return "confirmed"
    left = spots_left(capacity, attending)
    return "confirmed" if left is None or party_size <= left else "waitlisted"


def to_promote(capacity: int | None, attending: int, waitlist: list[tuple[int, int]]) -> list[int]:
    """Which waitlisted RSVPs fit now. `waitlist` is (rsvp_id, party_size), oldest first.

    Goes down the list in order and promotes every party that fits in the space
    left. A party too big for the remaining space is skipped (it keeps its place)
    rather than blocking smaller parties behind it.
    """
    left = spots_left(capacity, attending)
    promoted = []
    for rsvp_id, party_size in waitlist:
        if left is not None and party_size > left:
            continue
        promoted.append(rsvp_id)
        if left is not None:
            left -= party_size
    return promoted


def normalise_party_size(response: str, party_size: int) -> int:
    """A guest who says no isn't bringing anyone, so store 1."""
    return 1 if response == "no" else party_size


def capacity_too_low(new_capacity: int | None, attending: int) -> bool:
    """The host can't set capacity below the number of people already confirmed."""
    return new_capacity is not None and new_capacity < attending
