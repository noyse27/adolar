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

## API

- `GET /api/radio-stations`
- `POST /api/radio-stations`
- `PUT /api/radio-stations/<id>`
- `DELETE /api/radio-stations/<id>`
- `GET /api/radio-stations/<id>/tracks?count=25&shuffle_session=...`
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

Smart Shuffle blocks an exact track for 80 percent of the available station
pool. Artist and album cooldowns adapt to the number of tracks and distinct
values. Genres are distributed proportionally to their occurrence in the
candidate pool, so a dominant genre can still occur more often without forming
avoidable long runs. This genre distribution is disabled when the station has
an explicit genre rule, including a nested rule. Eligible candidates are scored
by recent artist/album occurrence, BPM distance from the previous planned
track, and a small random tie-breaker.

Jingles are represented as non-track queue items. They can be inserted every N
tracks per station and do not affect play counts, scrobbling, bookmarks, or
recently played history.
