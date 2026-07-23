# Testing Adolar4U

This guide describes the expected behavior of the metadata-first MVP. Restart
the server after switching to the feature branch so the database migration and
system-station seed run.

## 1. Activation and visibility

1. Log in as an administrator.
2. Open **Benutzerverwaltung** and enable **Adolar4U global bereitstellen**.
3. Open the personal **Adolar4U** entry in the user menu.
4. Enable **Persönliches Lernen aktivieren** and save.
5. Open the Radio panel.

Expected:

- `Adolar4U` is absent before both switches are enabled.
- It appears after global activation and personal opt-in.
- It remains hidden for anonymous visitors and users who did not opt in.
- Disabling either switch hides the station again.

## 2. Cold Start

Start `Adolar4U` before deliberately training it and listen to at least ten
transitions.

Expected:

- playback starts even when no Adolar4U events exist yet;
- existing play counts, favourites, Radio bookmarks, and personal playlists
  already influence selection;
- an unused account receives a varied library/discovery mix;
- Smart Shuffle still avoids unnecessary track, artist, album, and genre runs;
- Now Playing and Radio Companion show a short reason such as `Favorit`,
  `Häufig gehört`, or `Entdeckung`.

## 3. Positive and negative learning

Use a recognizable group of tracks or artists:

1. Let several desired tracks reach at least 90 percent.
2. Add one or two to a personal playlist or local Favorites.
3. Skip several unwanted tracks within their first 25 percent.
4. Restart the station after a few decisions.

Expected:

- completed, repeated, favourited, and playlist tracks gain weight;
- very early skips have a stronger negative effect than late skips;
- recently played tracks receive a temporary cooldown even when they are liked;
- related artists and genres gain a smaller affinity boost;
- results change gradually rather than becoming an immediate one-artist loop.

The radio preloads a queue. Newly recorded signals therefore affect the next
generated batch, not tracks already buffered. Switching to another station and
back requests a fresh queue and makes testing faster.

## 4. Discovery control

Compare the same account with the surprise slider at 0 and around 40 percent.
Restart the station after each change.

Expected:

- at 0 percent the candidate pool concentrates on established positive signals;
- at 40 percent more unheard or weakly connected tracks enter the candidate
  pool;
- discovery never disables Smart Shuffle spacing;
- exact sequences remain non-deterministic by design.

Small libraries or accounts without listening history will show less difference
between the two settings.

## 5. Pause and deletion

1. Enable **Lernen vorübergehend pausieren** and continue playback.
2. Resume learning and play another track.
3. Use **Lerndaten löschen**.

Expected:

- paused playback continues normally but records no new learning events;
- resuming starts collection again;
- deletion removes personal Adolar4U history but keeps the user's activation
  and discovery preference;
- after deletion the station falls back to existing play counts, favourites,
  and playlists.

## 6. Radio Companion

Log into the Radio Companion with the same opted-in account and reload its
station list.

Expected:

- `Adolar4U` appears only for that authenticated opted-in account;
- its queue is personalized for that account;
- completed tracks, manual Next actions, and crossfade transitions are recorded;
- a recommendation reason appears below the current artist.

## 7. Learning history

Open **Adolar4U -> Lernhistorie** after several station sessions and compare 7,
14, 30, and 60 days.

Expected:

- every selected track has the algorithm version, group, candidate rank, score,
  bonuses, penalties, and controlled random contribution that were current at
  selection time;
- completed and skipped outcomes attach to the exact decision, not merely to a
  nearby timestamp;
- group shares and average completion make long-session behavior visible;
- artist and genre changes compare the first and latest profile snapshots in
  the selected period;
- pausing learning creates no new diagnostic decisions;
- deleting personal learning data also deletes the journal;
- records older than 60 days are removed automatically.

Profile weights are normalized relative affinities. A change therefore means
that the relationship inside the profile changed; it is not an absolute
probability that the next track will use that artist or genre. The controlled
random contribution is deliberately shown so that a surprising selection is
not incorrectly explained as learned taste.

Use **Analyse-Export** in the history header to download the complete selected
period. The ZIP must contain `summary.json`, `recommendations.csv`,
`listening-events.csv`, `profile-batches.csv`, and `README.txt`. Verify that CSV
row counts match `summary.json`, recommendation outcomes link through
`recommendation_id`, Unicode artist/title values open correctly, and no data
from another Adolar user appears in the files.

## Not expected yet

The MVP does not yet analyze raw audio. Tonality, mood, energy, embeddings,
nightly profile generation, and collaborative recommendations from other users
are intentionally not part of this test. Their switches are placeholders for
later isolated milestones. The ordered handoff and the work immediately after
this test phase are documented in
[`adolar4u-roadmap.md`](adolar4u-roadmap.md).
