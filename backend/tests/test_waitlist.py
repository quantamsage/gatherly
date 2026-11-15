"""Waitlist, the guest's private manage link, and the CSV / calendar exports."""
import csv
import io

from tests.helpers import create_event, register, rsvp


def full_event(client, capacity=2):
    h = register(client)
    ev = create_event(client, h, capacity=capacity, waitlist_enabled=True)
    first = rsvp(client, ev["slug"], email="first@example.com", party_size=capacity)
    assert first.status_code == 201 and first.json()["status"] == "confirmed"
    return h, ev, first.json()


def guests(client, h, ev):
    return {g["email"]: g for g in client.get(f"/events/{ev['id']}/rsvps", headers=h).json()}


def test_yes_to_a_full_event_joins_the_waitlist_in_order(client):
    h, ev, _ = full_event(client)
    a = rsvp(client, ev["slug"], email="a@example.com").json()
    b = rsvp(client, ev["slug"], email="b@example.com", party_size=2).json()
    assert (a["status"], a["waitlist_position"]) == ("waitlisted", 1)
    assert (b["status"], b["waitlist_position"]) == ("waitlisted", 2)

    maybe = rsvp(client, ev["slug"], email="m@example.com", response="maybe").json()
    assert maybe["status"] == "confirmed" and maybe["waitlist_position"] is None

    event = client.get(f"/events/{ev['id']}", headers=h).json()
    assert event["counts"]["waitlisted"] == 2 and event["counts"]["attending"] == 2
    public = client.get(f"/public/events/{ev['slug']}").json()
    assert public["accepting_rsvps"] is True and public["spots_left"] == 0 and public["waitlist_enabled"] is True


def test_full_event_without_waitlist_still_refuses(client):
    h = register(client)
    ev = create_event(client, h, capacity=1)
    rsvp(client, ev["slug"], email="a@example.com")
    assert rsvp(client, ev["slug"], email="b@example.com").json()["error"]["code"] == "EVENT_FULL"


def test_guest_cancel_promotes_the_next_in_line(client):
    h, ev, first = full_event(client)
    rsvp(client, ev["slug"], email="a@example.com", party_size=2)
    rsvp(client, ev["slug"], email="b@example.com")

    assert client.delete(f"/public/rsvps/{first['manage_token']}").status_code == 204
    after = guests(client, h, ev)
    assert "first@example.com" not in after
    assert after["a@example.com"]["status"] == "confirmed" and after["a@example.com"]["promoted_at"]
    assert after["b@example.com"]["waitlist_position"] == 1
    assert client.get(f"/public/rsvps/{first['manage_token']}").status_code == 404  # link is dead now


def test_promotion_skips_a_party_that_does_not_fit(client):
    h, ev, first = full_event(client, capacity=3)
    rsvp(client, ev["slug"], email="big@example.com", party_size=3)
    rsvp(client, ev["slug"], email="small@example.com", party_size=1)

    res = client.patch(f"/public/rsvps/{first['manage_token']}", json={"party_size": 2})
    assert res.status_code == 200 and res.json()["party_size"] == 2
    after = guests(client, h, ev)
    assert after["small@example.com"]["status"] == "confirmed"
    assert after["big@example.com"]["status"] == "waitlisted" and after["big@example.com"]["waitlist_position"] == 1


def test_guest_can_only_lower_party_size(client):
    _, ev, first = full_event(client)
    res = client.patch(f"/public/rsvps/{first['manage_token']}", json={"party_size": 5})
    assert res.status_code == 409 and res.json()["error"]["code"] == "PARTY_SIZE_INCREASE"
    no = rsvp(client, ev["slug"], email="no@example.com", response="no").json()
    res = client.patch(f"/public/rsvps/{no['manage_token']}", json={"party_size": 1})
    assert res.json()["error"]["code"] == "NOT_ATTENDING"


def test_host_raising_capacity_or_removing_guest_promotes(client):
    h, ev, _ = full_event(client)
    rsvp(client, ev["slug"], email="a@example.com")
    rsvp(client, ev["slug"], email="b@example.com")
    rsvp(client, ev["slug"], email="c@example.com")

    updated = client.patch(f"/events/{ev['id']}", json={"capacity": 3}, headers=h).json()
    assert updated["counts"]["attending"] == 3 and updated["counts"]["waitlisted"] == 2

    b = guests(client, h, ev)["b@example.com"]
    first = guests(client, h, ev)["first@example.com"]
    assert client.delete(f"/events/{ev['id']}/rsvps/{first['id']}", headers=h).status_code == 204
    after = guests(client, h, ev)
    assert after["b@example.com"]["status"] == "confirmed" and after["c@example.com"]["status"] == "confirmed"
    assert b["waitlist_position"] == 1

    unlimited = client.patch(f"/events/{ev['id']}", json={"capacity": None}, headers=h).json()
    assert unlimited["counts"]["waitlisted"] == 0


def test_host_remove_is_private(client):
    h, ev, _ = full_event(client)
    gid = guests(client, h, ev)["first@example.com"]["id"]
    other = register(client, email="other@example.com")
    assert client.delete(f"/events/{ev['id']}/rsvps/{gid}", headers=other).status_code == 404
    assert client.delete(f"/events/{ev['id']}/rsvps/{gid}").status_code == 401
    assert client.delete(f"/events/{ev['id']}/rsvps/999999", headers=h).status_code == 404


def test_manage_link(client):
    _, ev, first = full_event(client)
    token = first["manage_token"]
    assert len(token) == 32
    mine = client.get(f"/public/rsvps/{token}").json()
    assert mine["event"]["slug"] == ev["slug"] and mine["status"] == "confirmed"
    assert "email" not in mine
    assert client.get("/public/rsvps/" + "x" * 32).status_code == 404
    assert client.get("/public/rsvps/short").status_code == 422


def test_token_is_stored_hashed(client, db_ready):
    import psycopg
    _, _, first = full_event(client)
    with psycopg.connect(db_ready) as conn:
        stored = conn.execute("SELECT manage_token_hash FROM rsvp_responses").fetchone()[0]
    assert stored != first["manage_token"] and len(stored) == 64


def test_guest_list_csv(client):
    h, ev, _ = full_event(client)
    rsvp(client, ev["slug"], email="w@example.com", name="=cmd|calc")
    rsvp(client, ev["slug"], email="n@example.com", response="no", name="Nope")
    res = client.get(f"/events/{ev['id']}/rsvps/export", headers=h)
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert [r["email"] for r in rows] == ["first@example.com", "w@example.com", "n@example.com"]
    assert rows[1]["status"] == "waitlisted" and rows[1]["waitlist_position"] == "1"
    assert rows[1]["name"].startswith("'=")
    other = register(client, email="other@example.com")
    assert client.get(f"/events/{ev['id']}/rsvps/export", headers=other).status_code == 404


def test_calendar_file(client):
    h = register(client)
    ev = create_event(client, h, title="Book club, vol 2", location="Café; upstairs")
    res = client.get(f"/public/events/{ev['slug']}/calendar.ics")
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/calendar")
    body = res.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Book club\\, vol 2" in body and "LOCATION:Café\\; upstairs" in body
    assert f"UID:{ev['slug']}@gatherly" in body
    assert client.get("/public/events/doesnotexist1/calendar.ics").status_code == 404
