# Radio Stations

Radio stations are a separate feature area from playlists.

## Model

`radio_stations` stores dynamic radio definitions:

- `name`: user-visible station name
- `description`: optional station description
- `filter_json`: JSON filter tree
- `is_system`: protected system station flag
- `created_by`, `created_at`, `updated_at`

The default station is `Adolar Radio` and is seeded as a system station. System
stations can be played by everyone, but cannot be edited or deleted.

## Permissions

- Admin users can create, edit, and delete non-system stations.
- Normal users can list and play stations.
- The companion `/radio` page uses the same station list and track endpoint.

## API

- `GET /api/radio-stations`
- `POST /api/radio-stations` admin only
- `PUT /api/radio-stations/<id>` admin only
- `DELETE /api/radio-stations/<id>` admin only
- `GET /api/radio-stations/<id>/tracks?count=25&exclude=...`

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

Station playback uses the same queue behavior as the original radio: load a
small initial queue, play immediately, and refill in the background while
excluding recently played track IDs.

Jingles, if added later, should be represented as non-track queue items so they
do not affect play counts, scrobbling, bookmarks, or recently played history.
