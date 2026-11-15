"use client";

import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import EventForm from "@/components/EventForm";
import HostTopbar from "@/components/HostTopbar";
import { api, ApiError, downloadFile, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { EventInput, HostEvent, Rsvp } from "@/lib/types";
import { useRequireAuth } from "@/lib/useRequireAuth";

export default function EventDetail() {
  const ready = useRequireAuth();
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [event, setEvent] = useState<HostEvent | null>(null);
  const [guests, setGuests] = useState<Rsvp[]>([]);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [ev, list] = await Promise.all([
        api<HostEvent>(`/events/${id}`, { auth: true }),
        api<Rsvp[]>(`/events/${id}/rsvps`, { auth: true }),
      ]);
      setEvent(ev);
      setGuests(list);
      setError("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(errorMessage(err));
    }
  }, [id, router]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  if (!ready) return null;
  if (!event) {
    return (
      <main className="page">
        <HostTopbar />
        {error ? <p className="error" role="alert">{error}</p> : <p className="muted">Loading…</p>}
      </main>
    );
  }

  const shareUrl = `${window.location.origin}/e/${event.slug}`;

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Couldn't copy automatically. Select the link and copy it.");
    }
  }

  async function update(changes: Partial<EventInput> & { rsvp_open?: boolean }) {
    const updated = await api<HostEvent>(`/events/${id}`, { method: "PATCH", body: changes, auth: true });
    setEvent(updated);
  }

  async function toggleOpen() {
    setBusy(true);
    try {
      await update({ rsvp_open: !event!.rsvp_open });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function exportGuests() {
    try {
      await downloadFile(`/events/${id}/rsvps/export`, `guests-${event!.slug}.csv`);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function removeGuest(guest: Rsvp) {
    const extra = guest.status === "confirmed" && event!.waitlist_enabled
      ? " Their spot goes to the next person on the waitlist." : "";
    if (!window.confirm(`Remove ${guest.name}'s reply?${extra}`)) return;
    try {
      await api(`/events/${id}/rsvps/${guest.id}`, { method: "DELETE", auth: true });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  async function remove() {
    if (!window.confirm("Delete this event and every RSVP? This can't be undone.")) return;
    try {
      await api(`/events/${id}`, { method: "DELETE", auth: true });
      router.push("/dashboard");
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  const c = event.counts;
  return (
    <main className="page">
      <HostTopbar />
      <h1>{event.title}</h1>
      <p className="muted">
        {formatDateTime(event.starts_at)}
        {event.location && `, ${event.location}`}
      </p>
      {error && <p className="error" role="alert">{error}</p>}

      <div className="stats">
        <div className="stat"><span className="num">{c.attending}{event.capacity ? `/${event.capacity}` : ""}</span>people coming</div>
        <div className="stat yes"><span className="num">{c.yes}</span>said yes</div>
        <div className="stat maybe"><span className="num">{c.maybe}</span>said maybe</div>
        <div className="stat no"><span className="num">{c.no}</span>said no</div>
        {event.waitlist_enabled && (
          <div className="stat maybe"><span className="num">{c.waitlisted}</span>on the waitlist</div>
        )}
      </div>

      <h3>Share this link with guests</h3>
      <div className="share">
        <input readOnly value={shareUrl} aria-label="Public RSVP link"
          onFocus={(e) => e.currentTarget.select()} />
        <button type="button" onClick={copyLink}>{copied ? "Copied" : "Copy link"}</button>
      </div>
      {!event.accepting_rsvps && (
        <p className="notice">
          This link isn't taking RSVPs right now
          {!event.rsvp_open ? " because you closed them." : (event.waitlist_enabled ? " because the event has started." : " because the event is full or has started.")}
        </p>
      )}

      <div className="toolbar">
        <button type="button" className="secondary" disabled={busy} onClick={toggleOpen}>
          {event.rsvp_open ? "Close RSVPs" : "Reopen RSVPs"}
        </button>
        {!editing && <button type="button" className="secondary" onClick={() => setEditing(true)}>Edit details</button>}
        <button type="button" className="secondary" onClick={load}>Refresh</button>
        <button type="button" className="secondary" onClick={exportGuests} disabled={guests.length === 0}>
          Export guest list (CSV)
        </button>
        <button type="button" className="danger" onClick={remove}>Delete event</button>
      </div>

      {editing && (
        <div style={{ marginBottom: "2rem" }}>
          <EventForm initial={event} submitLabel="Save changes"
            onSubmit={async (input) => { await update(input); setEditing(false); }}
            onCancel={() => setEditing(false)} />
        </div>
      )}

      <h2>Guest list</h2>
      {guests.length === 0 ? (
        <p className="empty">No replies yet. Share the link above to start collecting RSVPs.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Reply</th><th>Party</th><th>Email</th><th>Note</th><th aria-label="Actions" /></tr>
            </thead>
            <tbody>
              {guests.map((g) => (
                <tr key={g.id}>
                  <td>{g.name}</td>
                  <td>
                    {g.status === "waitlisted"
                      ? <span className="pill maybe">waitlist #{g.waitlist_position}</span>
                      : <span className={`pill ${g.response}`}>{g.response}</span>}
                    {g.promoted_at && <span className="muted small"> (from waitlist)</span>}
                  </td>
                  <td>{g.party_size}</td>
                  <td>{g.email}</td>
                  <td>{g.note}</td>
                  <td>
                    <button type="button" className="link" onClick={() => removeGuest(g)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
