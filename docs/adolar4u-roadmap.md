# Adolar4U: Current Status and Roadmap

This document is the short project handoff for Adolar4U. Read it before making
changes to the recommender. Detailed behavior is documented in
[`adolar4u.md`](adolar4u.md); the current manual test procedure is in
[`adolar4u-testing.md`](adolar4u-testing.md).

## TL;DR for the next task

- **Now:** private real-world validation of the metadata-first recommender.
- **Immediately next:** fix evidenced defects, calibrate group shares and
  weights, then freeze the baseline with regression tests.
- **Not next:** nightly profiles, audio embeddings, collaborative learning, or
  public release.
- **Later order:** optional profile snapshot -> local audio features -> hybrid
  ranking -> collaborative evaluation -> public-readiness review.
- **Operational requirement before public release:** guided, verified database
  restore with maintenance mode, emergency snapshot, and rollback path.
- Preserve the decisions in this document unless new test evidence justifies a
  deliberate change.

## Current status

Adolar4U is in a **private metadata-first validation phase**. It is not a public
feature and must remain hidden unless both the global switch and the individual
user opt-in are enabled.

Already implemented:

- privacy-aware listening events and personal learning controls;
- per-user play counts, playlists, local Favorites, and Last.fm Loved signals;
- a separate Last.fm account per Adolar user;
- one-way Favorite-to-Last.fm synchronization, enabled by default;
- deduplicated explicit taste signals: a local Favorite plus a Last.fm Loved
  entry is one preference, not two;
- anchor, similar, familiar, and discovery candidate groups;
- approximately 15 percent direct Favorite/Loved anchors when enough other
  candidates exist;
- a full-strength repeat cooldown for the first 24 hours, followed by a weaker
  cooldown through day seven;
- Smart Shuffle sequencing after personal ranking.
- a private 60-day learning journal with versioned decision details, aggregate
  group shares, profile changes, and exact outcome linkage.
- a user-scoped analysis export containing complete CSV decision/event/profile
  data and an aggregated JSON summary for the selected history period.

The existing installation had one user, who is the administrator. The former
global Last.fm connection and Loved cache are therefore migrated once to that
admin. The new model is nevertheless user-scoped for future accounts.

## Decisions that should not be casually reversed

1. Loved tracks and Favorites are taste evidence, not the bulk of the station.
2. Adding a local Favorite may add a Last.fm heart; removing the local Favorite
   does not remove the Last.fm heart.
3. Importing Last.fm Loved tracks does not silently create local Favorites.
4. The newest durable play or listening event controls recency. A track heard
   within 24 hours gets the same strong cooldown regardless of whether it was
   heard one hour or 23 hours ago.
5. Candidate membership is selected before Smart Shuffle performs spacing.
6. Adolar4U remains private until the metadata baseline is understandable and
   stable in real listening.
7. Raw-audio analysis, embeddings, nightly profile generation, and
   collaborative recommendations are not part of the current phase.
8. Skip penalties are smoothed ratios. A single early skip of a barely-heard
   track must remain a mild dampener; only repeated skips converge toward the
   full penalty. Before the smoothing (`SKIP_PENALTY_SMOOTHING` in
   `adolar4u/recommender.py`), one skip produced the same maximum penalty as
   ten skips and effectively banned the track, which real listening in July
   2026 showed to be too harsh.

## Current test phase

Use the Synology installation for normal listening over several days. Deliberate
short test runs are useful, but they do not replace ordinary long sessions.

The test should answer these questions:

- Do recently heard tracks stay out for roughly 24 hours when the library has
  alternatives?
- Do Favorite/Loved tracks appear occasionally without dominating the station?
- Does a large Last.fm Loved library influence similar artists and genres
  without turning Adolar4U into a Loved playlist?
- Does the discovery slider cause a noticeable but not chaotic change?
- Do early skips, completed tracks, personal playlists, and long-unheard tracks
  change later queues in the expected direction?
- Are recommendation reasons plausible?
- Does behavior remain sensible for repeated one-track queue requests from the
  Radio Companion or Android Auto?

When reporting a surprising selection, preserve the track, approximate time,
whether it was Favorite/Loved, when it last played, the recommendation reason,
and (if available) its `adolar4u_bucket`. Those facts are more useful than a
general impression that the mix felt repetitive.

## Next milestone after validation

The next committed milestone is **baseline evaluation and calibration**, not a
new AI subsystem:

1. Correct selection or event-recording defects found during real listening.
2. Compare observed long-session group shares with the intended shares.
3. Tune weights, thresholds, and group allocation only from repeatable evidence.
4. Use the private learning journal to inspect group shares, score drivers,
   profile changes, and listening outcomes; do not expose implementation
   buckets as a permanent public feature.
5. Freeze a metadata-first baseline and its regression tests.

Only after this baseline is trustworthy should the next larger milestone be
selected.

## Committed operational milestone: guided restore

The verified external backup system is implemented: it creates consistent
SQLite snapshots, checks them, records a checksum and manifest, includes radio
jingles, and retains completed backups outside the Docker data volume.

A **guided restore is still open and must not be forgotten**. It does not need
to interrupt the current private Adolar4U listening validation, but it is a
required durability milestone before public release or before presenting
restore as a normal administrator feature. This is especially important because
the database now contains personal accounts, Last.fm associations, Favorites,
and accumulated Adolar4U learning history.

The restore milestone is complete only when all of the following are covered:

1. An administrator can select a completed backup; partial backups can never be
   selected.
2. Adolar verifies the manifest version, SHA-256 checksum, SQLite
   `quick_check`, schema compatibility, and required free space before changing
   the live installation.
3. Adolar enters an explicit maintenance mode that rejects new database writes
   and pauses scanners, scheduled jobs, and recommendation-event collection.
4. A verified emergency snapshot of the current live database is created before
   replacement. A failed emergency snapshot cancels the restore.
5. The restored database is staged on the same filesystem and swapped
   atomically; stale `-wal` and `-shm` files can never be attached to it.
6. The matching radio-jingle archive is restored safely without allowing paths
   outside the configured data directory.
7. The application performs a controlled restart and validates database
   integrity, schema version, and representative row counts after startup.
8. A failed post-restore validation has a documented and tested rollback to the
   emergency snapshot.
9. Restore start, success, failure, and rollback are recorded in the admin audit
   log without exposing private backup contents.
10. Automated tests cover interrupted restores, corrupt or incompatible
    backups, missing USB storage, insufficient space, and successful rollback;
    at least one real Synology restore drill is documented.

Do not implement this as a simple live file-copy button. Until this milestone is
finished, backups remain fully usable for a documented manual migration, but
the maintenance UI must not imply that an in-app restore is already available.

## Later roadmap candidates

These phases are ordered, but they are not authorization to implement them as
part of an unrelated fix.

### 1. Versioned taste-profile snapshot

Evaluate a scheduled profile that summarizes Favorite/Loved, completion, skip,
artist, genre, and playlist affinities. A nightly job is one possible
implementation, but should only be added if live computation proves too noisy
or expensive. It must remain personal, reproducible, and rebuildable.

### 2. Local audio-feature foundation

Add background extraction for key, energy, mood, and versioned audio
embeddings. It must be opt-in globally, must not block scanning or playback, and
must support incremental rebuilds after the feature version changes.

### 3. Hybrid candidate and transition ranking

Combine the proven metadata profile with audio similarity and transition
quality. Preserve candidate-group limits, explainability, repeat cooldown, and
Smart Shuffle spacing.

### 4. Collaborative signals

Consider privacy-preserving aggregate co-listening only when the installation
actually has enough opted-in users to produce useful data. It has little value
for the current single-user installation.

### 5. Public-readiness phase

Before making Adolar4U public: finalize defaults, remove temporary diagnostics,
document resource use and privacy behavior, test upgrades and profile deletion,
and provide a clear rollback/disable path. The final user guide and in-product
help must explicitly explain the asymmetric Favorite/Last.fm behavior:

- adding an Adolar Favorite can also add the Last.fm heart when the default
  one-way synchronization is enabled;
- adding or importing a Last.fm Loved track never silently creates an Adolar
  Favorite or inserts it into the Favorites playlist;
- removing an Adolar Favorite does not remove the independent Last.fm heart.

This distinction must be described next to the star/heart controls and in the
Last.fm setup instructions, not only in internal architecture documentation.

## Explicit non-goals for small follow-up tasks

- Do not add cloud AI or upload library/listening data.
- Do not make Last.fm mandatory.
- Do not let Favorites bypass queue diversity or the repeat cooldown.
- Do not merge Adolar4U logic into stable Smart Shuffle.
- Do not enable unfinished audio or collaborative switches merely because the
  database fields or UI placeholders already exist.
- Do not publish Adolar4U while the current private validation is incomplete.

## Code map

- `adolar4u/recommender.py`: candidate retrieval, scoring, groups, and reasons
- `adolar4u/service.py`: settings, consent, and listening events
- `adolar4u/schema.py`: module-owned database schema
- `smart_shuffle.py`: final sequencing state, including cumulative group counts
- `db.py`: personal Last.fm, Favorites, migrations, and station integration
- `app.py`: APIs and synchronization jobs
- `tests/test_adolar4u.py`: regression and isolation tests
