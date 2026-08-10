# Backlog

Low-priority ideas that are currently hard or blocked, not committed work. Unlike
the roadmaps for individual features, entries here have no schedule. Revisit
them occasionally to check whether the blocker has gone away; otherwise leave
them alone.

Each entry: what the idea is, why it's blocked or hard right now, and what
would have to change for it to become worth doing.

## ReplayGain / MP3Gain tags during playback

**Idea:** Use existing loudness information from audio tags for optional
playback normalization. Prefer `REPLAYGAIN_TRACK_GAIN` for radio and shuffled
playback; where an album is played in sequence, optionally use
`REPLAYGAIN_ALBUM_GAIN`. Respect associated peak values to avoid clipping.
Recognize MP3Gain-related APEv2 metadata where it provides usable ReplayGain
values, but never rewrite the audio file or its tags during playback.

**Why later:** Gain has to be applied consistently in every player (web app,
`/radio`/Windows Companion and Android) and combined correctly with the user's
volume and both sides of a crossfade. MP3Gain tags also need careful
interpretation: undo/min-max bookkeeping is not automatically a playback-gain
value. Missing, malformed or extreme values must always fall back to unchanged
playback volume.

**Implementation outline:** Read and cache supported gain/peak fields during
scanning, expose normalized dB values with track metadata, clamp them to a safe
range, and calculate effective volume as user volume × replay gain × fade
curve. Add a user setting for Off / Track / Album (automatic radio behavior),
plus tests for mixed tagged/untagged queues, clipping prevention, crossfade and
all clients.

**Recheck trigger:** Prioritize when audible level jumps between library tracks
become a recurring playback complaint or when player/scanner work already
touches the relevant metadata path.

## LRCLIB Lyricsfile 1.0 support

**Idea:** Add support for LRCLIB's proposed YAML-based Lyricsfile format,
including optional word-level timing. Existing LRC and plain lyrics remain the
compatible fallback and must continue to work unchanged.

**Why later:** The rich format and its API integration are currently described
upstream as a concept and implementation plan. Building against it before the
optional `lyricsfile` field is stable in the production get/search API would
risk avoidable rework.

**Recheck trigger:** The field is observable and stable in LRCLIB's production
API, with representative fixtures available.

**Grooming:** See the
[Lyrics roadmap and Lyricsfile grooming](lyrics-roadmap.md) for the proposed
data model, priority rules, migration, client impact, work packages, and test
matrix.

## Spotify integration for new-release discovery

**Idea:** Surface real "new releases" alongside the static local MP3 library —
either by loading/playing Spotify playlists (e.g. an "Adolar Disco"), or by
pulling Spotify's Release Radar into the Adolar4U suggestion list.

**Why blocked:**

- Spotify removed API access to algorithmic/editorial playlists (Release Radar,
  Discover Weekly, Daily Mix) for newly registered apps in November 2024. Only
  apps with pre-existing extended-quota access keep it.
- Actual audio playback of Spotify tracks can't happen inside Adolar's own
  player (DRM); at best Adolar could remote-control an already-running Spotify
  Connect device, which requires the user to have Spotify Premium.
- There is no public Spotify endpoint to submit external/local plays back into
  Spotify's own recommendation system (no Last.fm-style scrobble API).

**Recheck trigger:** Spotify reopens algorithmic-playlist API access, or offers
a scrobble-equivalent endpoint. Unlikely but worth a periodic check.

**Fallback that isn't blocked:** New releases from artists already in the
library can be detected without the restricted endpoints — Spotify's artist
discography endpoint (albums by artist, sorted by release date) is not
algorithmic and remains open. This only covers "new album from an artist you
already know," not genuine discovery, but doesn't need Premium or a Connect
device. ListenBrainz (MusicBrainz Foundation) is a fully open alternative with
a real scrobble API and its own recommendation system, if local-play-based
recommendations are wanted independent of Spotify.
