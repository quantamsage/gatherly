// Shapes returned by the backend. Mirrors docs/openapi.yaml.

export type Answer = "yes" | "no" | "maybe";

export type Counts = { yes: number; no: number; maybe: number; waitlisted: number; attending: number };

export type RsvpStatus = "confirmed" | "waitlisted";

export type HostEvent = {
  id: number;
  slug: string;
  title: string;
  description: string;
  location: string;
  starts_at: string;
  capacity: number | null;
  rsvp_open: boolean;
  waitlist_enabled: boolean;
  accepting_rsvps: boolean;
  counts: Counts;
  created_at: string;
};

export type PublicEvent = {
  slug: string;
  title: string;
  description: string;
  location: string;
  starts_at: string;
  accepting_rsvps: boolean;
  spots_left: number | null;
  waitlist_enabled: boolean;
};

export type Rsvp = {
  id: number;
  name: string;
  email: string;
  response: Answer;
  party_size: number;
  note: string;
  status: RsvpStatus;
  waitlist_position: number | null;
  promoted_at: string | null;
  created_at: string;
};

export type RsvpConfirmation = {
  name: string;
  response: Answer;
  party_size: number;
  status: RsvpStatus;
  waitlist_position: number | null;
  manage_token: string;
};

export type GuestRsvp = {
  name: string;
  response: Answer;
  party_size: number;
  status: RsvpStatus;
  waitlist_position: number | null;
  event: { slug: string; title: string; location: string; starts_at: string };
};

export type EventInput = {
  title: string;
  description: string;
  location: string;
  starts_at: string;
  capacity: number | null;
  waitlist_enabled: boolean;
};
