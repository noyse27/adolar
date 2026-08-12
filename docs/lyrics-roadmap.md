# Lyrics: Current Status and Roadmap

## Summary

Adolar's current lyrics support remains the production baseline:

- local `.lrc` and `.txt` sidecars
- MP3 `SYLT` and `USLT` tags
- LRCLIB `syncedLyrics` and `plainLyrics`
- database caching, approval, search, selection, and editing

Support for LRCLIB's proposed **Lyricsfile 1.0** YAML format is a
**nice-to-have** enhancement. It is additive and is not a release blocker.
Classic synchronized LRC and plain lyrics must remain supported as fallbacks.

Implementation should start when LRCLIB exposes the optional `lyricsfile` field
reliably in its production get/search APIs and the format is sufficiently
stable. The concept currently describes the data format, while the upstream
repository describes the API work as an implementation plan.

## Compatibility contract

Source selection and representation selection are separate concerns.

### Source selection

Keep the existing local-first behavior:

1. Return the cached database record while it is valid or not due for retry.
2. When resolution is due, check the local sidecar.
3. Then check the MP3 tag.
4. Only then query the configured external provider.

A remote result must not silently replace a valid local or manually edited
result. Explicit search and selection by an authorized user may replace the
current result after confirmation.

### Representation selection

Within one provider result or stored record, use this priority:

1. Valid, non-empty Lyricsfile
2. Classic `syncedLyrics`
3. Classic `plainLyrics`
4. Instrumental/no-lyrics state

When Lyricsfile is present, preserve it as the richest source and derive the
classic line-synchronized and plain representations from it. Existing clients
can then continue to consume their current payloads.

If Lyricsfile is malformed, too large, or uses an unsupported version, record a
safe diagnostic and fall back to `syncedLyrics` or `plainLyrics` from the same
result. A bad rich representation must not make otherwise usable lyrics
unavailable.

## Format capabilities

Lyricsfile 1.0 is YAML with:

- metadata such as title, artist, album, duration, language, offset, and
  instrumental state
- optional plain lyrics
- synchronized lines with start and optional end times
- optional word-level synchronization inside each line

Word timing is the main capability not represented by the current Adolar data
model. Line timing and plain text can be derived for fallback clients.

## Proposed data model

Extend `track_lyrics` additively. Existing columns and records remain valid.
Suggested nullable columns:

- `lyricsfile_raw TEXT` — the validated original YAML
- `lyricsfile_version TEXT`
- `timing_json TEXT` — normalized line and word timing for runtime use
- `language TEXT`
- `offset_ms INTEGER`

The existing `plain_lyrics`, `synced_lyrics`, `format`, source, status, and
revision fields remain the compatibility representation and workflow state.

Do not normalize each word into a separate database row in the first version.
A bounded JSON timing document is simpler to migrate, read, and replace
atomically. Keeping the validated raw document also allows lossless export and
future re-parsing.

### Migration behavior

- Add nullable columns without backfilling all existing lyrics.
- Old database records continue to use LRC/plain fallback.
- New Lyricsfile results store raw and normalized data plus derived
  LRC/plain fields.
- The existing empty-result retry policy remains applicable; Lyricsfile support
  must not cause an immediate re-query of every track.
- A later background migration may enrich existing provider-backed records, but
  only after the live API behavior and rate impact are understood.

## Parser and security requirements

Lyricsfile must be treated as untrusted provider or local-file input.

- Use safe YAML loading only; never enable arbitrary YAML object construction.
- Apply the existing lyrics size limit to the raw input.
- Limit nesting depth, line count, word count, and text lengths.
- Validate integer timestamps and reasonable ranges.
- Accept missing optional end times and normalize offsets consistently.
- Reject unsupported versions as rich data while retaining classic fallback.
- Avoid returning parser internals or raw exception details to clients.
- Store the raw YAML only after size and structural validation.

The parser should produce one internal representation shared by provider,
sidecar, API, and tests.

## Provider and API changes

### LRCLIB adapter

Extend the provider result with an optional Lyricsfile payload. If LRCLIB
returns both rich and classic fields:

- validate and store Lyricsfile
- derive classic fields from it
- retain provider identifiers for later manual selection
- fall back to the returned classic fields if validation fails

Search candidates should indicate whether they contain word-synchronized,
line-synchronized, or plain lyrics.

### Adolar API

Keep all existing response fields and add optional capabilities, for example:

- `lyricsfile_available`
- `lyricsfile_version`
- `language`
- `offset_ms`
- normalized `lines`, whose entries may contain `end_ms` and `words`

Do not send raw YAML to every playback client by default. This avoids payload
bloat and keeps the public response format independent of YAML. A restricted
admin/edit or export endpoint can expose the raw document if needed.

Clients must ignore unknown optional fields, so a mixed-version deployment
continues to work.

## Local files and MP3 tags

The current Lyricsfile concept does not define an official sidecar filename or
extension. Until a stable convention exists:

- continue writing `.lrc` for synchronized lyrics
- continue writing `.txt` for plain lyrics
- continue writing derived `SYLT`/`USLT` data to supported MP3 tags
- do not place raw YAML in an arbitrary private MP3 tag

An optional raw Lyricsfile sidecar can be added later behind a setting after the
naming convention is decided. Possible Adolar-specific naming must be clearly
marked as such and not presented as an upstream standard.

## Editing semantics

Editing only a derived LRC/plain representation while retaining an older
Lyricsfile document would create two conflicting sources of truth.

For the initial implementation:

- a normal user edit makes the edited classic representation canonical
- clear or deactivate the current Lyricsfile payload and word timing
- preserve the usual revision/history information
- an explicit provider selection can install a fresh Lyricsfile document again

A dedicated rich editor with line and word timing can be considered separately.
It is not required for basic Lyricsfile ingestion and fallback support.

## Client impact

### Web

- Continue rendering plain and line-synchronized lyrics.
- Add word highlighting as progressive enhancement when normalized word timing
  exists.
- Search and result selection show the available synchronization quality.
- If rich rendering fails, immediately use the derived LRC/plain representation.

### Radio companion

Keep its current lightweight line/plain payload. Rich timing is optional and
must not be required for displaying lyrics.

### Android

Keep the current API fields as the baseline. Android can initially consume the
derived line/plain representation and add word highlighting in a later client
iteration.

## Work packages

| Package | Size | Scope |
| --- | --- | --- |
| WP0 — contract spike | S | Verify the live LRCLIB payload, collect fixtures, confirm version behavior, and revisit the sidecar convention. |
| WP1 — parser/domain | M | Safe YAML parser, schema validation, normalized timing model, and conversion to LRC/plain. |
| WP2 — database/provider | M | Additive migration, provider ingestion, raw/normalized storage, and fallback handling. |
| WP3 — API/Web | M | Optional rich API fields, capability badges, line/word rendering, and graceful fallback. |
| WP4 — Radio/Android | S–M | Compatibility tests first; optional richer rendering can be split into later work. |
| WP5 — persistence/editing | M | Editing invalidation rules, export, and optional raw sidecar once naming is stable. |
| WP6 — tests/docs | M | Fixtures, migration tests, security cases, client contracts, and operator documentation. |

WP0 is the only sensible early task. The remaining packages should wait for a
stable live contract to avoid implementing against a proposal that may change.

## Test coverage

At minimum, cover:

- legacy plain-only and LRC-only records
- Lyricsfile-only results
- Lyricsfile plus classic fields, with Lyricsfile taking precedence
- malformed or unsupported Lyricsfile with classic fallback
- instrumental results
- line start/end timing and offset handling
- word timing, missing word end times, Unicode, and whitespace
- excessive size, nesting, line count, word count, and invalid timestamps
- migration from an existing database with no new columns populated
- provider search, selection, approval, revisions, and retry scheduling
- user edits invalidating stale rich timing
- Web, Radio, and Android behavior when optional rich fields are absent
- sidecar/tag write failures without losing the database record

The parser and conversion layer should use upstream examples as fixtures plus
Adolar-specific malformed and boundary fixtures.

## Open decisions and risks

- When will LRCLIB expose the field in its production API?
- Will version `1.0` or field names change before rollout?
- Will an official sidecar extension/naming convention be defined?
- Is word-level highlighting worth implementing in all clients or only Web?
- Should raw YAML be export-only or editable by administrators?
- Which safe YAML dependency and version policy should Adolar use?
- How should provider enrichment be rate-limited for existing records?

## Definition of ready

The feature is ready for implementation when:

- the production `/api/get` and `/api/search` contract is observable
- representative live and official fixtures are available
- fallback and editing semantics are accepted
- the sidecar question is either standardized or explicitly deferred
- dependency and security limits are agreed

## Definition of done

- Existing plain and LRC behavior is unchanged.
- Valid Lyricsfile is stored losslessly and converted predictably.
- Invalid rich data falls back without breaking playback or the lyrics dialog.
- Old databases and mixed-version clients remain compatible.
- Manual search, approval, editing, retries, and history still work.
- Security, migration, API, Web, Radio, and Android tests pass.
- Operator documentation explains enablement, storage, and fallback behavior.

## Upstream references

- [LRCLIB API documentation](https://www.lrclib.net/docs)
- [Lyricsfile 1.0 concept](https://github.com/tranxuanthang/lrclib/blob/main/LYRICSFILE_CONCEPT.md)
- [Lyricsfile implementation plan](https://github.com/tranxuanthang/lrclib/blob/main/LYRICSFILE_IMPLEMENTATION_PLAN.md)
