# Adolar4U

> Project handoff: [`adolar4u-roadmap.md`](adolar4u-roadmap.md) records the
> current phase, fixed decisions, next milestone, and explicit non-goals.

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
- Radio Companion signal reporting for authenticated, opted-in users;
- a globally defined but individually visible `Adolar4U` system station;
- metadata-first personal ranking with Cold Start and controlled discovery;
- bounded anchor, similar, familiar, and discovery candidate groups;
- personal Last.fm Loved and local Adolar Favorites as deduplicated taste signals;
- recommendation reasons returned with each selected track;
- a private, versioned recommendation journal with exact score components,
  queue composition, profile snapshots, and linked listening outcomes;
- Smart Shuffle sequencing after personal candidate ranking.

The current ranking uses play counts, personal Last.fm Loved tracks, local
Adolar Favorites, personal playlists,
completion/skip history, early skips, recency, same-hour listening patterns,
artist/genre affinity, and the user's discovery setting. Skip penalties are
Bayesian-smoothed ratios: a single skip is a mild dampener, and only repeated
skips approach the full penalty (see roadmap decision 8). Audio embeddings,
key/mood/energy analysis, and collaborative ranking are later milestones; their
switches are marked as being in preparation in the UI.

## Data model

`adolar4u_user_settings` stores consent and preference state. The table is
deleted automatically with its user.

`adolar4u_listening_events` stores the minimum signal needed for future model
training. Events are deleted automatically with either their user or track.
Server-side completion ratios are derived from playback position and duration.

The event API never stores search text, IP addresses, filenames, free-form
client metadata, or another user's identity.

`adolar4u_recommendation_batches` stores one compact diagnostic snapshot for an
actual queue request. `adolar4u_recommendations` stores only selected tracks,
not every rejected library candidate. The returned decision ID links subsequent
listening events to the exact recommendation without timestamp guessing.
Diagnostic records are personal, obey learning pause, are retained for at most
60 days, and are removed with the personal learning history. A logging failure
must never prevent a playable queue.

Direct Loved/Favorite playback is capped through candidate groups. Explicit
favorites primarily seed artist and genre affinity and cannot fill an entire
queue when other candidate groups are available. The bucket label returned by
the experimental station is intended for verification while Adolar4U remains
disabled by default.

## API foundation

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/adolar4u/status` | Effective global/user state |
| `PUT` | `/api/adolar4u/settings` | Update personal consent and preferences |
| `DELETE` | `/api/adolar4u/profile` | Delete personal learning history |
| `POST` | `/api/adolar4u/events/<track_id>` | Record an allowed listening event |
| `GET` | `/api/adolar4u/history` | Private recommendation and learning journal |
| `GET` | `/api/adolar4u/history/export` | Personal ZIP export with complete CSV data for 1–60 days |
| `GET` | `/api/admin/adolar4u/settings` | Read global module switches |
| `PUT` | `/api/admin/adolar4u/settings` | Update global module switches |

All endpoints require an authenticated user. Administrative endpoints also
require the admin role.

The export is always scoped to the authenticated user. It contains a JSON
summary plus CSV files for recommendations, listening events, and profile
batches. It deliberately excludes credentials, Last.fm session keys, client
session identifiers, and music file paths.

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

## Manual verification

See [`adolar4u-testing.md`](adolar4u-testing.md) for activation, learning,
privacy, discovery, and Radio Companion test scenarios.
