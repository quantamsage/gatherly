"""Open routes for guests: view an event by its public link, RSVP, add it to a
calendar, and manage your own reply with the private link you got when you
replied. These never return other guests' names or emails."""

import hashlib
import secrets
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Path, Response

from app import repo
from app.calendar import build_ics
from app.db import get_conn
from app.errors import APIError
from app.promotion import promote_waitlist
from app.rsvp_logic import (
    is_accepting_rsvps, normalise_party_size, rsvp_rejection, rsvp_status, spots_left,
)
from app.schemas import (
    GuestEventSummary, GuestRsvp, GuestRsvpUpdate, PublicEvent, RsvpConfirmation, RsvpCreate,
)

router = APIRouter(prefix="/public", tags=["public"])

Slug = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,32}$")]
# secrets.token_urlsafe(24) is always 32 characters.
ManageToken = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{32}$")]


def not_found() -> APIError:
    return APIError(404, "NOT_FOUND", "This event link doesn't exist. Check it with the host.")


def rsvp_not_found() -> APIError:
    return APIError(404, "NOT_FOUND", "This RSVP link isn't valid. It may have been cancelled.")


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@router.get("/events/{slug}", response_model=PublicEvent)
def get_public_event(slug: Slug):
    with get_conn() as conn:
        row = repo.get_event_by_slug(conn, slug)
    if row is None:
        raise not_found()
    return PublicEvent(
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        location=row["location"],
        starts_at=row["starts_at"],
        accepting_rsvps=is_accepting_rsvps(
            row["rsvp_open"], row["starts_at"], row["capacity"], row["attending"],
            datetime.now(timezone.utc), row["waitlist_enabled"],
        ),
        spots_left=spots_left(row["capacity"], row["attending"]),
        waitlist_enabled=row["waitlist_enabled"],
    )


@router.get(
    "/events/{slug}/calendar.ics",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}}},
)
def event_calendar_file(slug: Slug):
    """An .ics file guests can add to Google Calendar, Outlook or Apple Calendar."""
    with get_conn() as conn:
        row = repo.get_event_by_slug(conn, slug)
    if row is None:
        raise not_found()
    return Response(
        content=build_ics(row, datetime.now(timezone.utc)),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{row["slug"]}.ics"'},
    )


@router.post("/events/{slug}/rsvps", response_model=RsvpConfirmation, status_code=201)
def create_rsvp(slug: Slug, body: RsvpCreate):
    party_size = normalise_party_size(body.response, body.party_size)
    with get_conn() as conn:
        # Lock the event row: if two guests try for the last spot at once,
        # the second waits, then sees the updated count.
        event = repo.lock_event_by_slug(conn, slug)
        if event is None:
            raise not_found()
        attending = repo.attending_count(conn, event["id"])
        rejection = rsvp_rejection(
            rsvp_open=event["rsvp_open"],
            starts_at=event["starts_at"],
            capacity=event["capacity"],
            attending=attending,
            response=body.response,
            party_size=party_size,
            now=datetime.now(timezone.utc),
            waitlist_enabled=event["waitlist_enabled"],
        )
        if rejection:
            raise APIError(409, *rejection)
        token = secrets.token_urlsafe(24)
        data = {
            **body.model_dump(),
            "party_size": party_size,
            "status": rsvp_status(event["capacity"], attending, body.response, party_size),
            "manage_token_hash": hash_token(token),
        }
        row = repo.create_rsvp(conn, event["id"], data)
        if row is None:
            raise APIError(
                409, "ALREADY_RESPONDED",
                "This email has already replied. Use the private link from your confirmation to change it.",
            )
    return RsvpConfirmation(
        name=body.name, response=body.response, party_size=party_size,
        status=row["status"], waitlist_position=row["waitlist_position"], manage_token=token,
    )


def _guest_view(row: dict) -> GuestRsvp:
    return GuestRsvp(
        name=row["name"], response=row["response"], party_size=row["party_size"],
        status=row["status"], waitlist_position=row["waitlist_position"],
        event=GuestEventSummary(slug=row["slug"], title=row["title"],
                                location=row["location"], starts_at=row["starts_at"]),
    )


@router.get("/rsvps/{token}", response_model=GuestRsvp)
def get_my_rsvp(token: ManageToken):
    with get_conn() as conn:
        row = repo.find_rsvp_by_token(conn, hash_token(token))
    if row is None:
        raise rsvp_not_found()
    return _guest_view(row)


@router.patch("/rsvps/{token}", response_model=GuestRsvp)
def shrink_my_party(token: ManageToken, body: GuestRsvpUpdate):
    """Guests can bring fewer people (never more: that could push past capacity
    ahead of the waitlist). Freed spots go to the waitlist straight away."""
    with get_conn() as conn:
        row = repo.find_rsvp_by_token(conn, hash_token(token))
        if row is None:
            raise rsvp_not_found()
        event = repo.lock_event_by_id(conn, row["event_id"])
        if event["starts_at"] <= datetime.now(timezone.utc):
            raise APIError(409, "RSVP_CLOSED", "This event has already started.")
        if row["response"] == "no":
            raise APIError(409, "NOT_ATTENDING", "You've said you're not coming, so there's no party size to change.")
        if body.party_size > row["party_size"]:
            raise APIError(409, "PARTY_SIZE_INCREASE",
                           "You can only lower your party size here. Contact the host to bring more people.")
        repo.set_party_size(conn, row["id"], body.party_size)
        promote_waitlist(conn, event["id"], event["capacity"])
        return _guest_view(repo.find_rsvp_by_token(conn, hash_token(token)))


@router.delete("/rsvps/{token}", status_code=204)
def cancel_my_rsvp(token: ManageToken):
    """Withdraw your reply completely. If you had a spot, the next guest on the waitlist gets it."""
    with get_conn() as conn:
        row = repo.find_rsvp_by_token(conn, hash_token(token))
        if row is None:
            raise rsvp_not_found()
        event = repo.lock_event_by_id(conn, row["event_id"])
        repo.delete_rsvp(conn, event["id"], row["id"])
        promote_waitlist(conn, event["id"], event["capacity"])
    return Response(status_code=204)
