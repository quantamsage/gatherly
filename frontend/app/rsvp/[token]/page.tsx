"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { api, calendarUrl, errorMessage } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { GuestRsvp } from "@/lib/types";

const LABELS = { yes: "Going", maybe: "Maybe", no: "Can't go" } as const;

/** A guest's private page, reached from the link shown after they reply. No account needed. */
export default function ManageRsvpPage() {
  const { token } = useParams<{ token: string }>();
  const path = `/public/rsvps/${encodeURIComponent(token)}`;
  const [rsvp, setRsvp] = useState<GuestRsvp | null>(null);
  const [loadError, setLoadError] = useState("");
  const [partySize, setPartySize] = useState(1);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [cancelled, setCancelled] = useState(false);

  useEffect(() => {
    api<GuestRsvp>(path)
      .then((r) => {
        setRsvp(r);
        setPartySize(r.party_size);
      })
      .catch((err) => setLoadError(errorMessage(err)));
  }, [path]);

  async function saveParty(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api<GuestRsvp>(path, { method: "PATCH", body: { party_size: partySize } });
      setRsvp(updated);
      setMessage("Saved. Any spots you gave up have gone to the next guests on the waitlist.");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!confirm("Cancel your reply? If you had a spot, it goes to the next person on the waitlist.")) return;
    setBusy(true);
    setError("");
    try {
      await api<void>(path, { method: "DELETE" });
      setCancelled(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (loadError) {
    return <main className="page"><div className="ticket ticket-top"><p className="error">{loadError}</p></div></main>;
  }
  if (!rsvp) {
    return <main className="page"><p className="muted" style={{ textAlign: "center" }}>Loading your reply…</p></main>;
  }

  const { event } = rsvp;
  return (
    <main className="page">
      <article className="ticket">
        <div className="ticket-top">
          <p className="muted small" style={{ marginTop: 0 }}>Your reply to</p>
          <h1>{event.title}</h1>
          <div className="ticket-meta">
            <span><strong>When</strong> {formatDateTime(event.starts_at)}</span>
            {event.location && <span><strong>Where</strong> {event.location}</span>}
          </div>
        </div>

        <div className="perforation" aria-hidden="true" />

        <div className="ticket-bottom">
          {cancelled ? (
            <div role="status">
              <p>Your reply has been cancelled. Thanks for letting the host know.</p>
              <Link href={`/e/${event.slug}`}>Reply again</Link>
            </div>
          ) : (
            <>
              {error && <p className="error" role="alert">{error}</p>}
              {message && <p className="notice" role="status">{message}</p>}
              <div role="status">
                {rsvp.status === "waitlisted" ? (
                  <>
                    <span className="stamp maybe">Waitlist #{rsvp.waitlist_position}</span>
                    <p>
                      Hi {rsvp.name}. You&apos;re number {rsvp.waitlist_position} on the waitlist
                      {rsvp.party_size > 1 ? ` for ${rsvp.party_size} people` : ""}. You&apos;ll move up
                      automatically when a spot opens. Check back here to see your place.
                    </p>
                  </>
                ) : (
                  <>
                    <span className={`stamp ${rsvp.response}`}>{LABELS[rsvp.response]}</span>
                    <p>
                      Hi {rsvp.name}. Your reply is &ldquo;{LABELS[rsvp.response]}&rdquo;
                      {rsvp.response !== "no" && rsvp.party_size > 1 ? ` for ${rsvp.party_size} people` : ""}.
                    </p>
                  </>
                )}
              </div>

              {rsvp.response !== "no" && rsvp.party_size > 1 && (
                <form onSubmit={saveParty}>
                  <label>
                    Bringing fewer people?
                    <input type="number" min={1} max={rsvp.party_size} required value={partySize}
                      onChange={(e) => setPartySize(Number(e.target.value))} />
                  </label>
                  <button type="submit" disabled={busy || partySize === rsvp.party_size}>
                    {busy ? "Saving…" : "Update party size"}
                  </button>
                </form>
              )}

              <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap", marginTop: "1.25rem" }}>
                {rsvp.response !== "no" && <a href={calendarUrl(event.slug)}>Add to calendar (.ics)</a>}
                <button type="button" className="danger" onClick={cancel} disabled={busy}>
                  Cancel my reply
                </button>
              </div>
            </>
          )}
        </div>
      </article>
    </main>
  );
}
