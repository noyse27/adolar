# Adolar v1.11.0

Release date: 2026-09-04

## Highlights

- Songster playlist curation is now completed on the Adolar side: curated
  Songster playlists can be managed through the admin flow and served through
  the product-token-gated Songster routes.
- The web player can add whole albums to playlists, so album-first browsing can
  feed directly into static playlist building.
- Removed Songster playlists now surface more clearly after the next sync cycle,
  avoiding stale assumptions in downstream clients.

## Maintenance

- Added Dependabot version updates and refreshed CI action versions.
- Updated Python and Docker dependencies through the current dependency PRs.
- Documented the safer Synology Git deploy path and cleaned up the split
  Android/Companion repository layout.

## Notes

- This release follows `v1.10.0` and closes the playlist work from 2026-08-26
  and 2026-08-30 that was already on `main` but not yet tagged or documented as
  a release.
