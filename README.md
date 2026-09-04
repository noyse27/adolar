# Adolar

Current version: **1.11.0**

A self-hosted music archive web app for Synology NAS (or any Docker host). Browse, search, and stream your local MP3/FLAC/M4A collection from any browser — no cloud required.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Full-text search** — title, artist, album, genre (SQLite FTS5), spinning loader indicator, 500ms debounce
- **Facet filters** — dedicated artist/title/album fields plus genre, decade, year range, duration, format, bitrate, and BPM range; active filters combine with AND logic
- **Album-first browsing** — the album search shows a grid of matching albums instead of every track; double-click (or the open button) drills into one album's tracks in order, with a back button to return; various-artists compilations are grouped as a single card using a real album-artist tag, falling back to a folder heuristic until a library has been rescanned
- **Mobile player mode** — phone-first layout with full-width track list, off-canvas filters, and compact bottom player
- **Now Playing view** — focused full-screen playback view with large cover, synchronized controls, queue, radio context, and live date/time
- **Cover art** — 80×80 WebP thumbnails cached on filesystem, colored initials fallback; full-size for Radio
- **Fast paging** — COUNT cached after first page, subsequent pages skip DB count entirely
- **HTTP range streaming** — seekable audio in the browser
- **Resilient NAS streaming** — bounded Gunicorn thread workers isolate slow or paused audio clients instead of timing out an entire worker
- **Configurable radio stations** — global and private smart radio stations with admin/user ownership, filter builder, relative “date added” rules, test mode, and optional station jingles
- **Smart Shuffle** — shuffle the complete current search, filter result, or static playlist with session-wide track cooldown, dynamic artist/album spacing, proportional genre distribution, BPM-smoothed transitions, and an automatically refilled 100-track queue; explicit genre filters remain untouched
- **Radio playback** — equal-power crossfade (12s out / 8s in), next track pre-buffered; crossfade skipped for short tracks and station jingles
- **Optional library crossfade** — persistent crossfade switch for normal playback, playlists, and shuffled queues; kept separate from Radio playback
- **Atomic playback handoff** — the Web player keeps the already-buffered incoming audio slot, refills radio queues off the critical path, and validates buffered duration before fading
- **Android clients** — the separate [Adolar Android repository](https://github.com/noyse27/adolar-android) provides Adolar Radio and Adolar Next, including native Media3 playback and optional mobile sync back to this server
- **Clear Radio exit** — stop the active station and return directly to the library from the Radio button or Now Playing view
- **AdolarRadio** — separate [Windows companion app](https://github.com/noyse27/adolar-companion): native window, auto-starts radio, About dialog, buildable to `.exe`
- **Mini-player** — popup window with cover art, controls, progress bar, Last.fm love button
- **Download basket** — select tracks, export as ZIP
- **BPM support** — reads TBPM tag (Mixmeister-compatible), background librosa analysis for untagged tracks, writes result back to file tag; BPM shown in search results and filter
- **Background scanner** — indexes library without blocking UI, skips unchanged files (mtime), generates cover thumbnails after scan
- **Personal Last.fm accounts** — every signed-in user can connect an independent account for scrobbling, Loved tracks, and play-count imports
- **Adolar Disco badge** — shows 🪩 Disco in topbar when Adolar Disco is connected
- **User authentication** — first-run admin setup, optional additional accounts, account deactivation, remember-me login, and brute-force protection
- **Capability-based permissions** — playlist creation, private radio stations, downloads, and archive play-count contribution can be controlled without granting maintenance rights
- **Optional guest access** — Adolar Web can expose the read-only library, global playlists, and global radio while keeping personal and administrative actions locked
- **Configurable Radio Companion access** — public, authenticated users only, or disabled
- **Administrative audit log** — records user, capability, password-reset, account-status, and global access-setting changes without logging listening history
- **Per-user play counts** — each user tracks their own play history; optionally authorized users contribute plays to a durable archive count
- **Durable archive counts** — the highest value from database, Last.fm, or file tag wins; changed tags are written nightly or manually
- **Playlists** — smart playlists, static playlists, four global system playlists, and one protected personal Favorites playlist per user
- **Playlist editor** — visual editor with track search, rule-based smart filters including relative “date added” periods, drag-and-drop ordering, random fill, and portable `.adolarplaylist` import/export
- **Smart rules** — a separate natural-language editor turns German rule descriptions into explicit AND/OR groups while keeping the conventional editor available for simple filters
- **Database backups** — consistent SQLite snapshots with integrity check, SHA-256 checksum, jingle archive, daily automatic runs, and retention policy
- **Connection monitor** — admin overview of connected clients with heartbeats and masked IP addresses
- **Background job monitor** — admin System Monitor shows currently running and recently finished library scans, BPM analysis, thumbnail generation, database optimization, and backups, with progress and manual/automatic trigger
- **Local Favorites** — a star works without Last.fm; optionally and by default, adding a favorite also loves it on the connected Last.fm account
- **Private Adolar4U learning journal** — records versioned score components, candidate groups, profile snapshots, and listening outcomes; a personal ZIP export provides analysis-ready CSV and JSON files
- **Bookmark button** — add any track to a personal playlist directly from the track list; create new playlists on the fly
- **Radio favorites** — the Radio companion uses the same personal Favorites list as the Web player
- **DE / EN interface** — language switch in topbar

## What's new in 1.11.0

- **Songster playlist curation completed** — admins can create and maintain
  Songster-ready playlists from Adolar, including product-token-gated access
  for the Songster client and clearer status handling when removed playlists
  disappear on the next sync.
- **Albums can be added to playlists from the web player** — album browsing
  and playback flows now support sending full albums into playlists without
  leaving the player context.
- **Safer self-hosted operations** — local Synology Git deploy documentation,
  repo-split cleanup for Android/Companion clients, Dependabot coverage, CI
  action updates, and dependency refreshes are included in this release.

## What's new in 1.10.0

- **Adolar Next merged into main** — the offline-first Android player,
  its mobile-sync backend (device tokens, track matching, idempotent
  event batch), and the unified favorite/Last.fm love handling are now
  part of the main codebase. See the "Adolar Android" section below and
  the `android-next-0.1.0-beta` release for the APK.
- **Unified Last.fm love/unlove** — removing a favorite now unloves it on
  a connected Last.fm account (with `auto_love_favorites` enabled), the
  same way adding one already loved it. Previously unfavoriting left a
  stale Last.fm love in place. Applies to both the web UI and Android.
- **Songster integration (step 1)** — radio stations can be marked
  curated for the Songster game client and hidden from the normal
  station picker; a global on/off switch and admin settings gate the
  feature; an admin UI manages Songster playlists; the game client gets
  its own authenticated, product-token-gated track-matching, playlist,
  and audio-streaming routes.
- **API tokens now carry a product** — the "Neuer Token" dialog lets an
  admin pick Taggster or Songster when creating a token, instead of
  every token silently defaulting to Taggster; the token list shows each
  token's product.
- Fixed Adolar Disco's BPM callback (`POST /api/track/<id>/bpm`) being
  unreachable — it's called unauthenticated but was blocked by
  `before_request()` before its own (redundant) admin check ever ran.
- New **"Vollständiger Scan"** admin button forces a full re-read of every
  file's tags, bypassing the mtime-skip — needed when a scanner change
  starts extracting a field (e.g. `original_year`) that untouched files
  were never re-read for. The existing quick scan is now labeled
  "Schnellscan".
- Added `tracks.original_year` (from TDOR/ORIGINALYEAR/ORIGINALDATE) to
  distinguish a compilation's release year from its songs' original
  years — written by Adolar Taggster, read-only in Adolar itself.

## What's new in 1.9.0

- Smart rules provide a separate natural-language input for complex station and
  playlist filters. Album, artist and title use exact matches; genre uses
  `contains` so linked genres remain eligible. Value lists understand comma,
  `oder` and context-sensitive `und`, including phrases such as
  `Album enthält Bravo und Ronny und als Jahrzehnt 1980, 1990 oder 2000`.
- Playback now keeps a bounded previous-track history in the main Web player,
  the standalone Radio view and Android. Previous restarts the current track
  after five seconds and otherwise returns to the preceding track without
  discarding the newer crossfade and preload pipeline.
- The Flask backend is organized as the `adolar` package with route blueprints,
  reducing the former monolithic application module while preserving the
  existing entry points.
- A lyrics implementation roadmap and an optional Windows LRCLIB tray helper
  are included under `docs/` and `tools/lrclib-windows-tray/`.

## What's new in 1.8.0

- Radio stations and smart playlists can filter tracks by when they were added:
  either older than a period (`before`) or added within the most recent number
  of days, weeks, months, or years (`within the last`).
- Track records now keep an immutable `added_at` timestamp separate from the
  last indexing time. Re-indexing a changed file no longer makes it appear as
  newly added, and the global **Newest 100** playlist now sorts by the stable
  addition time. Existing libraries are migrated automatically on startup;
  their previous `indexed_at` value is retained as the best available initial
  addition time.

## What's new in 1.7.1

- Administrators can always open the lyrics tool for the current track, including
  tracks where automatic lookup found nothing. Missing lyrics are indicated by a
  red microphone; manual searches can adjust title, artist, and album without
  persisting unsuccessful query changes.

## What's new in 1.7.0

- Optional Lyrics module: local sidecar/tag lookup first, then the LRCLIB provider (self-hostable URL); synced-line display with live highlighting during playback; per-user "Lyrics bearbeiten" capability to search alternate matches, pick a different result, or free-edit the text; admin settings and a manual "check missing lyrics" background scan
- API tokens for external admin tools such as Adolar Taggster: `Authorization: Bearer` auth as an alternative to the browser session, managed from a new "API-Zugriff" settings section, shown in the connection monitor
- Adolar Taggster external-sync support: an admin endpoint to keep track paths in sync after an external rename/move, and a folder-scoped rescan that skips the full-library BPM/thumbnail sweep; scan completion time now survives a process restart
- Adolar4U: corrected completion normalization for browser-crossfade edge cases, a fresh shuffle session now seeds from the durable 12-hour candidate-group balance instead of restarting with another anchor, and the radio queue refills in smaller batches so it adapts faster to fresh listening signals
- Search now folds non-Latin scripts (e.g. Cyrillic) correctly instead of only ASCII case-folding
- Security: fixed a stored-XSS gap in the admin "Gesperrte IPs" panel, brought lyrics error responses in line with the existing curated-message convention, and locked down the CI workflow's default token permissions

## What's new in 1.6.0

- Album-first browsing: the album search filter now shows a grid of matching albums instead of every matching track; double-click opens one album's tracks in order, with a back button to return to the grid
- Various-artists compilations grouped correctly as a single album card using a real album-artist tag read from file metadata, instead of exploding into one card per contributing artist; existing libraries fall back to a folder-based heuristic until their next rescan populates the new tag
- Admin System Monitor now shows currently running and recently finished background jobs — library scan, BPM tag reading, BPM analysis, thumbnail generation, database optimize, and backups — with progress, start time, and whether each was manually or automatically triggered

## What's new in 1.5.0

- Visual playlist editor with track search, rule-based smart filters, portable `.adolarplaylist` import/export, drag-and-drop ordering, and random fill
- Personal Last.fm accounts: every signed-in user can connect their own account for scrobbling, Loved tracks, and play-count imports
- Local Favorites with a protected personal Favorites playlist per user; optional one-way sync to Last.fm Loved (enabled by default)
- Database backup system: consistent SQLite snapshots with integrity check, SHA-256 checksum, jingle archive, daily automatic backups, and retention policy — managed under Wartung → Datensicherung
- Admin connection monitor with client heartbeats and masked IP addresses
- Resilient NAS streaming through bounded Gunicorn thread workers; Last.fm calls moved to a background queue so network outages cannot stall requests
- Adolar Android companion app for playback and personal learning on the go
- Specific, curated validation messages across the playlist, filter, and radio APIs to make problems easier to pin down
- Security hardening: exception details never reach API responses, and the login redirect target is strictly normalized to same-origin paths

## What's new in 1.4.0

- Capability-based access control for personal playlists, private radio stations, downloads, and global play-count contribution
- Optional read-only guest access to Adolar Web with a visible login entry point
- Configurable Radio Companion access: public, authenticated users only, or disabled
- Account deactivation with immediate session revocation and an administrative audit log
- Server-enforced admin protection for scans, BPM maintenance, and other administrative operations
- Faster cold starts through a per-user stale-while-revalidate track cache and prioritized first-page loading
- Preloaded and atomically swapped Now Playing artwork for smoother crossfade transitions
- Genre-aware Smart Shuffle that proportionally distributes genres in library and radio playback, while respecting explicit genre filters

## Development notes

- [Adolar4U current status and roadmap](docs/adolar4u-roadmap.md)
- [Adolar4U architecture and privacy model](docs/adolar4u.md)
- [Adolar4U private validation guide](docs/adolar4u-testing.md)
- [Lyrics roadmap and Lyricsfile grooming](docs/lyrics-roadmap.md)

The Python server lives in the `adolar/` package. `adolar/application.py` owns
configuration, request context, and schedulers; HTTP endpoints are grouped by
feature in `adolar/routes/` Flask blueprints. `wsgi.py` is the production entry
point, while `run.py` starts a local installation. Maintenance commands that
are not part of the server package live in `scripts/`. Client applications are
maintained separately in [noyse27/adolar-android](https://github.com/noyse27/adolar-android)
and [noyse27/adolar-companion](https://github.com/noyse27/adolar-companion).

## Quick Start (Docker)

```yaml
# docker-compose.yml
services:
  adolar:
    build: .
    container_name: adolar
    ports:
      - "15002:5000"
    volumes:
      - /your/music:/music:ro
      - adolar-data:/data
      - /your/backup/location:/backups
    environment:
      MUSIC_ROOT: /music
      DB_PATH: /data/adolar.db
      BACKUP_PATH: /backups
```

```bash
docker compose up -d
# Open http://your-server:15002
# Then scan your library via the sidebar button
```

The container runs two Gunicorn `gthread` workers with four request threads
each. Long or paused audio streams can therefore outlive the worker timeout
without making the process appear frozen. Compose allows 30 seconds for a
graceful Gunicorn shutdown before forcing the container to stop. Non-critical
Last.fm Now Playing and scrobble calls use a small background queue; a Last.fm
network outage cannot hold an Adolar web request open.

## Quick Start (ohne Docker)

```bash
pip install -r requirements.txt
python run.py        # or double-click run.bat on Windows
```

`run.py` reads config from a local `.env` file if present (real environment
variables always take priority), then starts the same Gunicorn worker
configuration Docker uses (Linux/macOS only — Gunicorn does not support
Windows, so on Windows `run.py` falls back to Flask's development server,
which is fine for personal/local use but not for unattended production
hosting).

`MUSIC_ROOT` has no safe default (your library path is always personal), so
on first run `run.py` asks for it interactively and saves it to `.env` —
subsequent runs won't ask again. `DB_PATH` and `BACKUP_PATH` fall back to
`~/.cache/adolar/...` if left unset, so they don't need to be configured
before the first run.

## Database backups

The live SQLite database stays in the Docker-managed `adolar-data` volume. A
separate bind mount exposes `/backups` on the host; the Synology compose example
defaults to `/volumeUSB1/usbshare/adolarDBbackup`. Create that directory before
starting the container. Compose is configured with `create_host_path: false`, so
the container fails safely instead of silently writing to the NAS system disk
when the USB share is absent.

Administrators can create, inspect, download, and delete snapshots under
**Wartung → Datensicherung**. Adolar uses SQLite's online backup mechanism, runs
`PRAGMA quick_check`, calculates a SHA-256 checksum, and only then publishes the
backup directory. Uploaded radio jingles are stored alongside the database as a
small archive. Interrupted `.partial` directories are never shown as valid
backups.

By default, one automatic snapshot is created daily after 03:00 and the newest
seven snapshots are retained. The host location and policy can be changed in
`.env`:

```dotenv
SECRET_KEY=change_me_to_a_long_random_hex_value
BACKUP_HOST_PATH=/volumeUSB1/usbshare/adolarDBbackup
BACKUP_AUTO_ENABLED=true
BACKUP_HOUR=3
BACKUP_RETENTION=7
TZ=Europe/Berlin
```

`SECRET_KEY` should be set to one stable random value on long-running servers;
otherwise Flask creates a new secret on every container start and existing
browser sessions can be invalidated. On Synology installs that use this repo
directly, keep the Compose project name stable as well. The known production
layout on `Vault_II` uses project name `musicapp`, so updates should run through
[`scripts/update-syno.sh`](scripts/update-syno.sh) or explicitly use
`docker compose -p musicapp up -d --build adolar`. See
[`docs/synology-git-deploy.md`](docs/synology-git-deploy.md) for the first-time
conversion from copied deploys to a real Git checkout.

The backup contains personal accounts, Last.fm sessions, favorites, and
Adolar4U learning data. Protect the directory accordingly and copy it to a
second device or destination with Synology Hyper Backup. A backup on the same
NAS alone does not protect against disk or device failure.

A guided in-app restore is a committed operational milestone in the
[Adolar4U/project roadmap](docs/adolar4u-roadmap.md). Until its maintenance
mode, emergency snapshot, atomic replacement, restart validation, and rollback
path are implemented and tested, restoration remains a documented manual
migration operation.

## Pre-generate Cover Thumbnails

For large libraries, pre-generate all thumbnails before first use:

```bash
docker exec adolar pip install Pillow   # first time only
docker exec -it adolar python scripts/generate_thumbs.py --workers 4
```

Thumbnails are stored in `/data/thumbs/` (persistent volume) and survive container restarts.
Cover images failing with `--verbose` are corrupt embedded tags — normal, they get a colored placeholder.

## BPM Workflow

1. **Mixmeister BPM Analyzer** — run over your library to write TBPM tags
2. **"BPM-Tags einlesen"** button in Adolar sidebar — reads tags into DB instantly
3. **"BPM berechnen"** button — runs librosa analysis in background for tracks without tags, writes result back into file tag

## AdolarRadio (Windows Companion)

Source and releases now live in [noyse27/adolar-companion](https://github.com/noyse27/adolar-companion).
Download the latest `.exe` from its [Releases](https://github.com/noyse27/adolar-companion/releases).
Connect it to your Adolar server in the settings dialog. An optional Adolar login unlocks personal stations and radio bookmarks; connection and login state are restored on the next start.

## Adolar Android

Source and releases now live in [noyse27/adolar-android](https://github.com/noyse27/adolar-android).
Two independent Android apps, installable side by side (different application IDs, no shared data):

- **Adolar Radio** (`net.polze.adolarradio`) — the original Android companion: native station picker and playback controls, Android Auto support, connected to your Adolar server.
- **Adolar Next** (`net.polze.adolarnext`, currently beta) — an offline-first local music player with its own library, playlists, and favorites (Room-backed, works without a server), plus optional background sync: local play history, favorites, and Last.fm love/unlove mirror to your Adolar account once connected. See [the Android README](https://github.com/noyse27/adolar-android#readme) and [`docs/android-local-library.md`](docs/android-local-library.md) for the architecture.

Download the latest APKs from the Android repo's [Releases](https://github.com/noyse27/adolar-android/releases) and sideload (enable "Install unknown apps" for your file manager/browser). Both are debug-signed builds for sideloading, not Play Store releases.

## First Run

On first start, navigate to `/setup` to create the admin account. All subsequent users are added by the admin via the user management panel (topbar → admin menu).

## User manual

The responsive German user manual for Adolar Web and Adolar Radio Companion is available at [`/hilfe/manual.html`](hilfe/manual.html). It includes quick starts, playback, filters, playlists, radio stations, Companion login, permissions, maintenance, troubleshooting, full-text chapter search, and a print layout.

## Access control and permission matrix

Adolar uses three visible access levels (`Admin`, `User`, and `Anonymous`) plus individual user capabilities. Permissions are checked by the server; hiding a control in the interface is not used as an authorization mechanism.

| Capability | Admin | User | Anonymous |
|---|:---:|:---:|:---:|
| Use Adolar Web and browse the library | Always | Yes | Configurable |
| Play tracks | Yes | Yes | Yes when anonymous Web is enabled |
| Use global playlists | Yes | Yes | Yes when anonymous Web is enabled |
| Create and manage personal playlists | Yes | Global setting + per-user permission | No |
| Listen to global radio stations | Yes | Yes | Yes |
| Create and manage private radio stations | Yes | Global setting + per-user permission | No |
| Create or edit global radio stations | Yes | No | No |
| Download tracks | Yes | Per-user permission | No |
| Maintain a personal play count | Yes | Yes | No |
| Contribute plays to the archive/global count | Yes | Per-user setting | No |
| Connect and use a personal Last.fm account | Yes | Yes | No |
| Scan the library and run BPM maintenance | Yes | No | No |
| Manage users, blocked IPs, and access settings | Yes | No | No |
| View the administrative audit log | Yes | No | No |

Global access settings in the user-management panel:

| Setting | Values | Default |
|---|---|---|
| Anonymous Adolar Web | Enabled / disabled | Disabled |
| Personal playlists for users | Enabled / disabled | Enabled |
| Private radio stations for users | Enabled / disabled | Enabled |
| Radio Companion | Public / authenticated users / disabled | Public |

Disabling playlist or radio creation does not delete existing personal content. Deactivated accounts keep their content and play-count history, but all active sessions are revoked immediately.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MUSIC_ROOT` | `/music` | Path to music library |
| `DB_PATH` | `/data/adolar.db` | SQLite database path |
| `BACKUP_PATH` | `/backups` | Initial backup directory; admin-editable afterward under Datenbank-Wartung without a restart |
| `BACKUP_HOST_PATH` | `/volumeUSB1/usbshare/adolarDBbackup` | Host directory mounted at `/backups` by Compose |
| `BACKUP_AUTO_ENABLED` | `true` in Compose | Enable the daily verified snapshot |
| `BACKUP_HOUR` | `3` | Local hour after which the daily backup starts |
| `BACKUP_RETENTION` | `7` | Number of completed snapshots to retain |
| `TZ` | `Europe/Berlin` | Time zone used by scheduled maintenance jobs |
| `SECRET_KEY` | random | Flask session secret — set a fixed value to survive restarts |
| `LASTFM_API_KEY` | — | Last.fm API key (optional) |
| `LASTFM_API_SECRET` | — | Last.fm API secret (optional) |
| `CORS_ORIGINS` | `` | Allowed CORS origins (space-separated) |

## API Endpoints (selection)

| Method | Path | Description |
|---|---|---|
| GET | `/api/search` | Search with filters + pagination (`count=0` skips COUNT) |
| GET | `/api/shuffle?count=N` | Smart-shuffle the current search/filter or static playlist; continue via `shuffle_session` response header |
| GET | `/api/random?count=N` | N smart-shuffled tracks; continue via `shuffle_session` from the response header |
| GET | `/api/radio-stations` | List playable radio stations |
| GET | `/api/radio-stations/<id>/tracks` | Get smart-shuffled tracks for a radio station |
| POST | `/api/radio-stations/<id>/jingle` | Upload a station jingle (station owner/admin) |
| GET | `/api/stream/<id>` | Stream audio (range requests supported) |
| GET | `/api/cover/<hash>` | Cover thumbnail (80×80 WebP); `?full=1` for original |
| POST | `/api/scan/start` | Start library scan (admin only) |
| POST | `/api/scan/bpm-tags` | Read BPM from file tags into DB (admin only) |
| POST | `/api/scan/bpm` | Background librosa BPM analysis (admin only) |
| GET/POST | `/api/admin/backups` | List or start verified backups (admin only) |
| DELETE | `/api/admin/backups/<id>` | Delete a completed backup (admin only) |
| GET | `/api/adolar4u/history/export?days=60` | Download the current user's private analysis export |
| POST | `/api/track/<id>/bpm` | Write BPM value (used by Adolar Disco) |
| POST | `/api/track/<id>/played` | Increment per-user play count (auth required) |
| POST | `/api/track/<id>/disco-played` | Increment Disco play count (public, never writes file) |
| GET | `/api/disco-status` | Check if Adolar Disco is connected |
| GET | `/api/playlists` | List global plus personal playlists; global-only for anonymous access |
| POST | `/api/playlists` | Create playlist (playlist capability required) |
| POST | `/api/playlists/<id>/tracks` | Add track to static playlist (auth required) |
| GET | `/api/me` | Current user info (auth required) |
| GET | `/api/me-optional` | Current user info or null (public) |

© PolzeSoft 2026 · [polze.net](https://polze.net) · adolar@polze.net
