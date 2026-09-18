# Radio Stations

Radio stations are a separate feature area from playlists.

## Model

`radio_stations` stores dynamic radio definitions:

- `name`: user-visible station name
- `description`: optional station description
- `filter_json`: JSON filter tree
- `scope`: `global` or `private`
- `owner_id`: owner for private stations
- `jingle_path`, `jingle_every_tracks`, `jingle_enabled`: optional station ID audio
- `is_system`: protected system station flag
- `created_by`, `created_at`, `updated_at`

The default station is `Adolar Radio` and is seeded as a system station. System
stations can be played by everyone, but cannot be renamed, edited, or deleted.
Admins can still upload, configure, and remove a jingle for the default station.

## Permissions

- Admin users can create, edit, and delete global stations and can inspect/delete
  private stations.
- Normal users can create and edit only their own private stations.
- Anonymous companion users see only global stations.
- The companion `/radio` page uses the same station list and track endpoint.
- In the main Web UI, opening a playlist or library result does not stop an
  active station. While browsing, the active station button changes to a return
  action and restores the current queue; pressing it again from the queue stops
  the radio. Background queue refills must never replace the browsed list.

## API

- `GET /api/radio-stations`
- `POST /api/radio-stations`
- `PUT /api/radio-stations/<id>`
- `DELETE /api/radio-stations/<id>`
- `GET /api/radio-stations/<id>/tracks?count=25&shuffle_session=...`
- `PATCH /api/radio-stations/<id>/enabled` with `{"enabled": true|false}`
- `POST /api/radio-stations/<id>/jingle`
- `PATCH /api/radio-stations/<id>/jingle`
- `DELETE /api/radio-stations/<id>/jingle`
- `GET /api/radio-stations/<id>/jingle`

## Filter JSON

Filters are stored as data, never as SQL. The server validates the tree and
translates only known fields and operators to parameterized SQL.

Example:

```json
{
  "mode": "all",
  "rules": [
    {"field": "playcount", "op": "lt", "value": 1},
    {"field": "decade", "op": "eq", "value": 1980},
    {
      "mode": "any",
      "rules": [
        {"field": "genre", "op": "contains", "value": "Synthpop"},
        {"field": "genre", "op": "contains", "value": "Dark Wave"}
      ]
    }
  ]
}
```

Allowed text fields: `title`, `artist`, `album`, `genre`.

Allowed text operators: `contains`, `not_contains`.

Allowed numeric fields: `year`, `decade`, `playcount`.

Allowed numeric operators: `eq`, `ne`, `gt`, `lt`.

`genre contains Synthpop` intentionally matches combined genre strings such as
`EBM/Synthpop`.

## Playback

Station playback loads a small initial queue, plays immediately, and refills in
the background. The server returns an `X-Shuffle-Session` header; passing that
value back as `shuffle_session` preserves the planned track, artist, album,
genre-run, and BPM history across queue refills.

Normal radios and library shuffle finish a complete song cycle before allowing
repeats. Artist/title variants on different albums count as one song. Skipping
a queued song advances the cycle. Sessions are persisted in
`CONTROL_DB_PATH + ".shuffle.db"` and shared across Gunicorn workers; the active
library is part of the session context. Adolar4U retains its adaptive shortlist
cooldown behavior. Artist and album cooldowns adapt to the number of tracks and distinct
values. Genres are distributed proportionally to their occurrence in the
candidate pool, so a dominant genre can still occur more often without forming
avoidable long runs. This genre distribution is disabled when the station has
an explicit genre rule, including a nested rule. Eligible candidates are scored
by recent artist/album occurrence, BPM distance from the previous planned
track, and a small random tie-breaker.

Jingles are represented as non-track queue items. An enabled station jingle is
played once when the station starts and then again every N tracks. Jingles do
not affect play counts, scrobbling, bookmarks, or recently played history.
The tracks endpoint advertises `X-Radio-Jingle-Every` (zero when disabled) so
Adolar Next can insert jingles at startup and across batch boundaries.

`Loved on Last.fm` is a private managed station with engine `lastfm_loved` and
`configuration_locked=true`. Its definition and jingle configuration cannot be
edited or deleted, including by admins. The owner can only toggle `enabled`;
the preference survives Last.fm syncs and status refreshes. Disabled stations
return no tracks. Existing Loved stations are upgraded during database startup.

INFO logs include shuffle context, cycle, candidate count, history size and
selected track IDs; radio queue logs also include the session and load duration.
