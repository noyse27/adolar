# Adolar4U

**Deine Musik. Deine Mission.**

Adolar4U is an optional, privacy-first personalization module. It is developed
separately from the stable Smart Shuffle and must have no behavioral or runtime
cost when disabled.

## Activation and consent

All switches default to off.

1. An administrator enables Adolar4U globally.
2. Each user explicitly enables personal learning.
3. Learning can be paused without deleting the profile.
4. Collaborative signals require both global permission and personal opt-in.
5. A user can delete their personal learning history at any time.

Creating the module tables is not consent to collect data. The event endpoint
rejects collection unless the global and personal switches are both active.

## Current foundation

The first implementation milestone provides:

- isolated `adolar4u` Python package;
- global module, audio-analysis, and collaborative-learning switches;
- personal learning, pause, collaborative, and discovery settings;
- privacy-aware `started`, `skipped`, and `completed` listening events;
- playback position, duration, source, transition reason, and session context;
- client event identifiers for idempotent retries;
- personal history deletion;
- Web-player signal reporting, including manual skips, natural completion,
  crossfades, track changes, radio exit, and page exit.

It does not yet rank tracks or expose the final Adolar4U station. Until that
ranking engine exists, normal radio and Smart Shuffle behavior remains the only
playback path.

## Data model

`adolar4u_user_settings` stores consent and preference state. The table is
deleted automatically with its user.

`adolar4u_listening_events` stores the minimum signal needed for future model
training. Events are deleted automatically with either their user or track.
Server-side completion ratios are derived from playback position and duration.

The event API never stores search text, IP addresses, filenames, free-form
client metadata, or another user's identity.

## API foundation

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/adolar4u/status` | Effective global/user state |
| `PUT` | `/api/adolar4u/settings` | Update personal consent and preferences |
| `DELETE` | `/api/adolar4u/profile` | Delete personal learning history |
| `POST` | `/api/adolar4u/events/<track_id>` | Record an allowed listening event |
| `GET` | `/api/admin/adolar4u/settings` | Read global module switches |
| `PUT` | `/api/admin/adolar4u/settings` | Update global module switches |

All endpoints require an authenticated user. Administrative endpoints also
require the admin role.

## Planned ranking pipeline

The recommendation engine will remain hybrid and explainable:

1. Retrieve candidates from personal history, metadata, audio similarity, and
   aggregate co-listening signals.
2. Score taste fit, time context, replay affinity, skip risk, novelty, and the
   configured discovery share.
3. Add transition quality from BPM, key, energy, and mood.
4. Pass ranked candidates to Smart Shuffle for track, artist, album, and genre
   spacing.
5. Return a short reason that can support a future "Why this track?" UI.

Audio extraction and embeddings will be background jobs with versioned feature
records. They must not run when global audio analysis is disabled and must never
block streaming or library scans.
