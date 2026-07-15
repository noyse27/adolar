# Adolar

Current version: **1.2.1**

A self-hosted music archive web app for Synology NAS (or any Docker host). Browse, search, and stream your local MP3/FLAC/M4A collection from any browser — no cloud required.

![Python](https://img.shields.io/badge/Python-3.12-blue)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Full-text search** — title, artist, album, genre (SQLite FTS5), spinning loader indicator, 500ms debounce
- **Facet filters** — genre, decade, year range, duration, format, bitrate, BPM range, artist/title initial
- **Mobile player mode** — phone-first layout with full-width track list, off-canvas filters, and compact bottom player
- **Cover art** — 80×80 WebP thumbnails cached on filesystem, colored initials fallback; full-size for Radio
- **Fast paging** — COUNT cached after first page, subsequent pages skip DB count entirely
- **HTTP range streaming** — seekable audio in the browser
- **Configurable radio stations** — global and private smart radio stations with admin/user ownership, filter builder, test mode, and optional station jingles
- **Smart Shuffle** — session-wide track cooldown, dynamic artist/album spacing, and BPM-smoothed transitions with controlled randomness
- **Radio playback** — equal-power crossfade (12s out / 8s in), next track pre-buffered; crossfade skipped for short tracks and station jingles
- **AdolarRadio** — Windows companion app: native window, auto-starts radio, About dialog, buildable to `.exe`
- **Adolar Radio Android** — Android companion project with phone WebView and Android Auto media playback for local developer installs
- **Mini-player** — popup window with cover art, controls, progress bar, Last.fm love button
- **Download basket** — select tracks, export as ZIP
- **BPM support** — reads TBPM tag (Mixmeister-compatible), background librosa analysis for untagged tracks, writes result back to file tag; BPM shown in search results and filter
- **Background scanner** — indexes library without blocking UI, skips unchanged files (mtime), generates cover thumbnails after scan
- **Last.fm scrobbling** — auto-scrobble + love tracks; loved status cached locally for instant display (no per-page API calls)
- **Adolar Disco badge** — shows 🪩 Disco in topbar when Adolar Disco is connected
- **User authentication** — first-run setup, login with remember-me, brute-force protection (IP ban after 10 failed attempts), admin-managed user accounts
- **Per-user permissions** — admin controls download access per user; Last.fm and scan functions are admin-only
- **Per-user play counts** — each user tracks their own play history; optionally authorized users contribute plays to a durable archive count
- **Durable archive counts** — the highest value from database, Last.fm, or file tag wins; changed tags are written nightly or manually
- **Playlists** — smart playlists (saved filter/sort state) and static playlists; 4 system playlists for all users (Recently played, Most played, Newest 100, Disco Hits)
- **Bookmark button** — add any track to a personal playlist directly from the track list; create new playlists on the fly
- **Radio bookmarks** — log in via Adolar Radio companion to bookmark tracks into a personal "Radio Favourites" playlist
- **DE / EN interface** — language switch in topbar

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
    environment:
      MUSIC_ROOT: /music
      DB_PATH: /data/adolar.db
```

```bash
docker compose up -d
# Open http://your-server:15002
# Then scan your library via the sidebar button
```

## Pre-generate Cover Thumbnails

For large libraries, pre-generate all thumbnails before first use:

```bash
docker exec adolar pip install Pillow   # first time only
docker exec -it adolar python generate_thumbs.py --workers 4
```

Thumbnails are stored in `/data/thumbs/` (persistent volume) and survive container restarts.
Cover images failing with `--verbose` are corrupt embedded tags — normal, they get a colored placeholder.

## BPM Workflow

1. **Mixmeister BPM Analyzer** — run over your library to write TBPM tags
2. **"BPM-Tags einlesen"** button in Adolar sidebar — reads tags into DB instantly
3. **"BPM berechnen"** button — runs librosa analysis in background for tracks without tags, writes result back into file tag

## AdolarRadio (Windows Companion)

Download the latest `.exe` from [Releases](https://github.com/noyse27/adolar/releases).
Enter your Adolar server URL in the settings dialog, click Save & Start — radio begins immediately.

## Adolar Radio Android

Open [`adolar-android`](adolar-android) in Android Studio to install the app directly to your phone via USB debugging. It stores your Adolar server URL, opens `/radio` in a WebView on the phone, and exposes a simple Android Auto media service for random radio playback.

## First Run

On first start, navigate to `/setup` to create the admin account. All subsequent users are added by the admin via the user management panel (topbar → admin menu).

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MUSIC_ROOT` | `/music` | Path to music library |
| `DB_PATH` | `/data/adolar.db` | SQLite database path |
| `SECRET_KEY` | random | Flask session secret — set a fixed value to survive restarts |
| `LASTFM_API_KEY` | — | Last.fm API key (optional) |
| `LASTFM_API_SECRET` | — | Last.fm API secret (optional) |
| `CORS_ORIGINS` | `` | Allowed CORS origins (space-separated) |

## API Endpoints (selection)

| Method | Path | Description |
|---|---|---|
| GET | `/api/search` | Search with filters + pagination (`count=0` skips COUNT) |
| GET | `/api/random?count=N` | N smart-shuffled tracks; continue via `shuffle_session` from the response header |
| GET | `/api/radio-stations` | List playable radio stations |
| GET | `/api/radio-stations/<id>/tracks` | Get smart-shuffled tracks for a radio station |
| POST | `/api/radio-stations/<id>/jingle` | Upload a station jingle (station owner/admin) |
| GET | `/api/stream/<id>` | Stream audio (range requests supported) |
| GET | `/api/cover/<hash>` | Cover thumbnail (80×80 WebP); `?full=1` for original |
| POST | `/api/scan/start` | Start library scan (admin only) |
| POST | `/api/scan/bpm-tags` | Read BPM from file tags into DB (admin only) |
| POST | `/api/scan/bpm` | Background librosa BPM analysis (admin only) |
| POST | `/api/track/<id>/bpm` | Write BPM value (used by Adolar Disco) |
| POST | `/api/track/<id>/played` | Increment per-user play count (auth required) |
| POST | `/api/track/<id>/disco-played` | Increment Disco play count (public, never writes file) |
| GET | `/api/disco-status` | Check if Adolar Disco is connected |
| GET | `/api/playlists` | List user's playlists (auth required) |
| POST | `/api/playlists` | Create playlist (auth required) |
| POST | `/api/playlists/<id>/tracks` | Add track to static playlist (auth required) |
| GET | `/api/me` | Current user info (auth required) |
| GET | `/api/me-optional` | Current user info or null (public) |

© PolzeSoft 2026 · [polze.net](https://polze.net) · adolar@polze.net
