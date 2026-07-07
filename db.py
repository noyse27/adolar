import sqlite3
import os
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/adolar.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                path        TEXT    NOT NULL UNIQUE,
                title       TEXT,
                artist      TEXT,
                album       TEXT,
                genre       TEXT,
                year        INTEGER,
                track_no    INTEGER,
                duration    INTEGER,
                bitrate     INTEGER,
                size        INTEGER,
                cover_hash  TEXT,
                bpm         REAL,
                mtime       REAL,
                play_count  INTEGER NOT NULL DEFAULT 0,
                indexed_at  REAL DEFAULT (unixepoch())
            );

            CREATE TABLE IF NOT EXISTS covers (
                hash        TEXT PRIMARY KEY,
                data        BLOB NOT NULL,
                mime        TEXT NOT NULL DEFAULT 'image/jpeg'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
                title,
                artist,
                album,
                genre,
                content='tracks',
                content_rowid='id'
            );

            CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
                INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                VALUES (new.id, new.title, new.artist, new.album, new.genre);
            END;

            CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
                INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre)
                VALUES ('delete', old.id, old.title, old.artist, old.album, old.genre);
            END;

            CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
                INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre)
                VALUES ('delete', old.id, old.title, old.artist, old.album, old.genre);
                INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                VALUES (new.id, new.title, new.artist, new.album, new.genre);
            END;

            CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist COLLATE NOCASE);
            CREATE INDEX IF NOT EXISTS idx_tracks_album  ON tracks(album);
            CREATE INDEX IF NOT EXISTS idx_tracks_genre  ON tracks(genre);
            CREATE INDEX IF NOT EXISTS idx_tracks_year   ON tracks(year);
            CREATE INDEX IF NOT EXISTS idx_tracks_bpm    ON tracks(bpm);

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS lastfm_loved_tracks (
                artist_norm TEXT NOT NULL,
                title_norm  TEXT NOT NULL,
                artist      TEXT,
                title       TEXT,
                loved_at    INTEGER,
                synced_at   REAL DEFAULT (unixepoch()),
                PRIMARY KEY (artist_norm, title_norm)
            );

            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                username             TEXT    NOT NULL UNIQUE,
                password_hash        TEXT    NOT NULL,
                role                 TEXT    NOT NULL DEFAULT 'user',
                allow_download       INTEGER NOT NULL DEFAULT 0,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                created_at           TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at REAL    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS login_blocks (
                ip           TEXT PRIMARY KEY,
                blocked_until REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_play_counts (
                user_id        INTEGER NOT NULL,
                track_id       INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                count          INTEGER NOT NULL DEFAULT 0,
                last_played_at REAL,
                PRIMARY KEY (user_id, track_id)
            );
            CREATE INDEX IF NOT EXISTS idx_upc_user ON user_play_counts(user_id, count DESC);
            CREATE INDEX IF NOT EXISTS idx_upc_recent ON user_play_counts(user_id, last_played_at DESC);

            CREATE TABLE IF NOT EXISTS playlists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id   INTEGER,
                name       TEXT    NOT NULL,
                type       TEXT    NOT NULL DEFAULT 'smart',
                filters    TEXT    NOT NULL DEFAULT '{}',
                sort       TEXT    NOT NULL DEFAULT 'artist',
                is_system  INTEGER NOT NULL DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                added_at    REAL    DEFAULT (unixepoch()),
                PRIMARY KEY (playlist_id, track_id)
            );
            CREATE INDEX IF NOT EXISTS idx_plt_playlist ON playlist_tracks(playlist_id, added_at);
        """)
        # Seed system playlists (idempotent)
        _seed_system_playlists(conn)
        # Migrations (safe to run repeatedly)
        for migration in [
            "ALTER TABLE tracks ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tracks ADD COLUMN bpm REAL",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass


_SYSTEM_PLAYLISTS = [
    ("Zuletzt gespielt",    "recent",       "{}"),
    ("Meistgespielt",       "top_played",   "{}"),
    ("Neueste 100",         "newest_added", "{}"),
    ("Disco Hits",          "disco_top",    "{}"),
]

def _seed_system_playlists(conn):
    existing = {r[0] for r in conn.execute(
        "SELECT sort FROM playlists WHERE is_system=1"
    ).fetchall()}
    for name, sort, filters in _SYSTEM_PLAYLISTS:
        if sort not in existing:
            conn.execute(
                "INSERT INTO playlists (owner_id, name, filters, sort, is_system) VALUES (NULL,?,?,?,1)",
                (name, filters, sort)
            )


def _norm_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _like_pattern(value: str) -> str:
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def search_tracks(query="", artist_query="", title_query="", album_query="",
                  genre=None, decade=None, fmt=None,
                  min_dur=None, max_dur=None, min_bitrate=None,
                  year_min=None, year_max=None,
                  bpm_min=None, bpm_max=None,
                  page=1, per_page=50, sort="artist",
                  count=True, loved_only=False, include_loved=False,
                  user_id=None):
    params = []
    conditions = []

    if query:
        # Each word gets its own prefix wildcard: "extreme clubhits" → "extreme* clubhits*"
        fts_query = " ".join(w + "*" for w in query.split() if w)
        conditions.append(
            "t.id IN (SELECT rowid FROM tracks_fts WHERE tracks_fts MATCH ?)"
        )
        params.append(fts_query)

    if artist_query:
        conditions.append("LOWER(COALESCE(t.artist, '')) LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(artist_query.casefold()))
    if title_query:
        conditions.append("LOWER(COALESCE(t.title, '')) LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(title_query.casefold()))
    if album_query:
        conditions.append("LOWER(COALESCE(t.album, '')) LIKE ? ESCAPE '\\'")
        params.append(_like_pattern(album_query.casefold()))

    if genre:
        conditions.append("t.genre = ?")
        params.append(genre)
    if decade:
        try:
            d = int(decade)
            conditions.append("t.year >= ? AND t.year <= ?")
            params += [d, d + 9]
        except ValueError:
            pass
    if fmt:
        ext = "." + fmt.lower()
        conditions.append("LOWER(t.path) LIKE ?")
        params.append("%" + ext)
    if min_dur is not None:
        conditions.append("t.duration >= ?")
        params.append(int(min_dur))
    if max_dur is not None:
        conditions.append("t.duration <= ?")
        params.append(int(max_dur))
    if min_bitrate is not None:
        conditions.append("t.bitrate >= ?")
        params.append(int(min_bitrate))
    if year_min is not None:
        conditions.append("t.year >= ?")
        params.append(int(year_min))
    if year_max is not None:
        conditions.append("t.year <= ?")
        params.append(int(year_max))
    if bpm_min is not None:
        conditions.append("t.bpm >= ?")
        params.append(float(bpm_min))
    if bpm_max is not None:
        conditions.append("t.bpm <= ?")
        params.append(float(bpm_max))

    # loved JOIN — needed for loved_only filter, loved_at sort, or include_loved
    loved_join = ""
    loved_select = "0 AS loved, NULL AS loved_at"
    if loved_only or include_loved or sort == "loved_at":
        loved_join = """LEFT JOIN lastfm_loved_tracks l
                  ON l.artist_norm = LOWER(COALESCE(t.artist, ''))
                 AND l.title_norm = LOWER(COALESCE(t.title, ''))"""
        loved_select = "CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved, l.loved_at"
    if loved_only:
        conditions.append("l.artist_norm IS NOT NULL")

    # Play-count-based sort options — require JOIN on user_play_counts
    _PC_SORTS = {"recent", "top_played", "newest_added", "disco_top", "loved_at"}
    pc_join = ""
    pc_select = "0 AS user_play_count, NULL AS last_played_at"
    pc_uid = 0  # disco = user_id 0

    if sort in _PC_SORTS:
        if sort == "newest_added":
            order_expr = "t.indexed_at DESC"
        elif sort == "loved_at":
            # Sort by when track was loved on Last.fm (desc), loved tracks first
            order_expr = "l.loved_at DESC NULLS LAST, t.artist, t.title"
        elif sort == "recent":
            pc_uid = user_id or 0
            pc_join = f"LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id={int(pc_uid)}"
            pc_select = "COALESCE(upc.count,0) AS user_play_count, upc.last_played_at"
            conditions.append("upc.last_played_at IS NOT NULL")
            order_expr = "upc.last_played_at DESC"
        elif sort == "top_played":
            pc_uid = user_id or 0
            pc_join = f"LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id={int(pc_uid)}"
            pc_select = "COALESCE(upc.count,0) AS user_play_count, upc.last_played_at"
            order_expr = "upc.count DESC NULLS LAST, t.artist"
        else:  # disco_top
            pc_join = "LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id=0"
            pc_select = "COALESCE(upc.count,0) AS user_play_count, upc.last_played_at"
            conditions.append("upc.count > 0")
            order_expr = "upc.count DESC"
        order = order_expr
    else:
        sort_map = {
            "artist":   "t.artist, t.album, t.track_no",
            "title":    "t.title",
            "album":    "t.album, t.track_no",
            "year":     "t.year DESC, t.artist",
            "duration": "t.duration DESC",
        }
        order = sort_map.get(sort, sort_map["artist"])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    offset = (page - 1) * per_page

    # Always include user play count for display in track list
    if not pc_join:
        _uid = int(user_id or 0)
        pc_join = f"LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id={_uid}"
        pc_select = "COALESCE(upc.count,0) AS user_play_count, upc.last_played_at"

    # When filtering loved-only, deduplicate by artist+title (same song on multiple albums)
    # Keep the track with the highest play count, fall back to lowest track_no / album name
    if loved_only:
        dedup = f"""WITH ranked AS (
                SELECT t.id, t.path, t.title, t.artist, t.album, t.genre,
                       t.year, t.track_no, t.duration, t.bitrate, t.size,
                       t.cover_hash, t.bpm, {loved_select}, {pc_select},
                       ROW_NUMBER() OVER (
                           PARTITION BY LOWER(COALESCE(t.artist,'')), LOWER(COALESCE(t.title,''))
                           ORDER BY COALESCE(upc.count,0) DESC, t.album, t.track_no
                       ) AS rn
                FROM tracks t {loved_join} {pc_join} {where}
            )
            SELECT id, path, title, artist, album, genre, year, track_no, duration,
                   bitrate, size, cover_hash, bpm, loved, loved_at, user_play_count, last_played_at
            FROM ranked WHERE rn=1
            ORDER BY {order.replace("t.", "").replace("upc.", "").replace("l.", "")}
            LIMIT ? OFFSET ?"""
        count_sql = f"""WITH ranked AS (
                SELECT ROW_NUMBER() OVER (
                    PARTITION BY LOWER(COALESCE(t.artist,'')), LOWER(COALESCE(t.title,''))
                    ORDER BY t.id
                ) AS rn
                FROM tracks t {loved_join} {pc_join} {where}
            ) SELECT COUNT(*) FROM ranked WHERE rn=1"""
    else:
        dedup = f"""SELECT t.id, t.path, t.title, t.artist, t.album, t.genre,
                       t.year, t.track_no, t.duration, t.bitrate, t.size,
                       t.cover_hash, t.bpm, {loved_select}, {pc_select}
                FROM tracks t {loved_join} {pc_join} {where}
                ORDER BY {order}
                LIMIT ? OFFSET ?"""
        count_sql = f"SELECT COUNT(*) FROM tracks t {loved_join} {pc_join} {where}"

    with db() as conn:
        rows = conn.execute(dedup, params + [per_page, offset]).fetchall()

        if count:
            total = conn.execute(count_sql, params).fetchone()[0]
        else:
            total = offset + len(rows) + (1 if len(rows) == per_page else 0)

    def fmt_duration(s):
        if not s:
            return "0:00"
        m, sec = divmod(int(s), 60)
        return f"{m}:{sec:02d}"

    def file_format(path):
        import os
        return os.path.splitext(path)[1].lstrip(".").upper() if path else "MP3"

    tracks = []
    for r in rows:
        d = dict(r)
        d["duration_fmt"] = fmt_duration(d["duration"])
        d["format"] = file_format(d["path"])
        d["has_cover"] = bool(d["cover_hash"])
        d["loved"] = bool(d.get("loved"))
        tracks.append(d)

    return total, tracks


def replace_lastfm_loved_tracks(items: list[dict]):
    now = __import__("time").time()
    rows = [
        (
            _norm_text(item.get("artist")),
            _norm_text(item.get("title")),
            item.get("artist"),
            item.get("title"),
            item.get("loved_at"),
            now,
        )
        for item in items
        if _norm_text(item.get("artist")) and _norm_text(item.get("title"))
    ]
    with db() as conn:
        conn.execute("DELETE FROM lastfm_loved_tracks")
        conn.executemany(
            """INSERT OR REPLACE INTO lastfm_loved_tracks
               (artist_norm, title_norm, artist, title, loved_at, synced_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     ("lastfm_loved_synced_at", str(now)))
    return len(rows)


def get_loved_tracks_for_tag_write() -> list[dict]:
    """Return tracks that Last.fm says are loved, for writing the tag to disk."""
    with db() as conn:
        rows = conn.execute("""
            SELECT t.id, t.path, t.artist, t.title
            FROM tracks t
            JOIN lastfm_loved_tracks l
              ON LOWER(TRIM(COALESCE(t.artist,''))) = l.artist_norm
             AND LOWER(TRIM(COALESCE(t.title,'')))  = l.title_norm
        """).fetchall()
    return [dict(r) for r in rows]


def set_lastfm_loved(artist: str, title: str, loved: bool):
    artist_norm = _norm_text(artist)
    title_norm = _norm_text(title)
    if not artist_norm or not title_norm:
        return
    with db() as conn:
        if loved:
            conn.execute(
                """INSERT OR REPLACE INTO lastfm_loved_tracks
                   (artist_norm, title_norm, artist, title, loved_at, synced_at)
                   VALUES (?, ?, ?, ?, unixepoch(), unixepoch())""",
                (artist_norm, title_norm, artist, title),
            )
        else:
            conn.execute(
                "DELETE FROM lastfm_loved_tracks WHERE artist_norm=? AND title_norm=?",
                (artist_norm, title_norm),
            )


def get_lastfm_loved_status():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM lastfm_loved_tracks").fetchone()[0]
        row = conn.execute("SELECT value FROM settings WHERE key=?", ("lastfm_loved_synced_at",)).fetchone()
        synced_at = row["value"] if row else None
    return {"total": total, "synced_at": float(synced_at) if synced_at else None}


def get_genres():
    with db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT genre FROM tracks WHERE genre IS NOT NULL AND genre != '' ORDER BY genre"
        ).fetchall()
    return [r[0] for r in rows]


def get_stats():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
        size_row = conn.execute("SELECT SUM(size) FROM tracks").fetchone()
        size_gb = round((size_row[0] or 0) / 1_073_741_824, 1)
    return {"total_tracks": total, "total_size_gb": size_gb}


def get_random_tracks(count=25, exclude_ids=None):
    excl = exclude_ids or []
    with db() as conn:
        rows = conn.execute(
            f"""SELECT id, path, title, artist, album, genre, year, track_no,
                       duration, bitrate, size, cover_hash, bpm
                FROM tracks
                {"WHERE id NOT IN (" + ",".join("?"*len(excl)) + ")" if excl else ""}
                ORDER BY RANDOM() LIMIT ?""",
            excl + [count],
        ).fetchall()
    import os

    def _fmt(s):
        if not s: return "0:00"
        m, sec = divmod(int(s), 60)
        return f"{m}:{sec:02d}"

    def _file_format(path):
        return os.path.splitext(path)[1].lstrip(".").upper() if path else "MP3"

    tracks = []
    for r in rows:
        d = dict(r)
        d["duration_fmt"] = _fmt(d["duration"])
        d["format"] = _file_format(d["path"])
        d["has_cover"] = bool(d["cover_hash"])
        tracks.append(d)
    return tracks


def update_bpm(track_id: int, bpm: float) -> bool:
    """Store BPM for a track. Returns True if the track was found and updated."""
    with db() as conn:
        cur = conn.execute(
            "UPDATE tracks SET bpm=? WHERE id=? AND (bpm IS NULL OR bpm=0)",
            (bpm, track_id)
        )
        return cur.rowcount > 0


def get_scanner_status():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]
    return {"total_tracks": total}


def upsert_track(data: dict):
    data.setdefault("play_count", 0)
    data.setdefault("bpm", None)
    data.setdefault("loved", False)
    with db() as conn:
        conn.execute("""
            INSERT INTO tracks (path, title, artist, album, genre, year, track_no,
                                duration, bitrate, size, cover_hash, bpm, mtime, play_count, loved)
            VALUES (:path, :title, :artist, :album, :genre, :year, :track_no,
                    :duration, :bitrate, :size, :cover_hash, :bpm, :mtime, :play_count, :loved)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title, artist=excluded.artist, album=excluded.album,
                genre=excluded.genre, year=excluded.year, track_no=excluded.track_no,
                duration=excluded.duration, bitrate=excluded.bitrate, size=excluded.size,
                cover_hash=excluded.cover_hash, mtime=excluded.mtime,
                indexed_at=unixepoch(),
                play_count=MAX(play_count, excluded.play_count),
                bpm=CASE WHEN excluded.bpm IS NOT NULL THEN excluded.bpm ELSE bpm END,
                loved=CASE WHEN excluded.loved=1 THEN 1 ELSE loved END
        """, data)
        # Seed user_play_counts for admin (user_id=1) from file tag if not yet recorded
        if data.get("play_count", 0) > 0:
            conn.execute("""
                INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
                SELECT 1, id, ?, NULL FROM tracks WHERE path=?
                ON CONFLICT(user_id, track_id) DO NOTHING
            """, (data["play_count"], data["path"]))


def save_cover(hash_: str, data: bytes, mime: str = "image/jpeg"):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO covers (hash, data, mime) VALUES (?, ?, ?)",
            (hash_, data, mime),
        )


def increment_play_count(track_id: int):
    """Increments play_count by 1 in DB, returns (new_count, path)."""
    with db() as conn:
        conn.execute(
            "UPDATE tracks SET play_count = play_count + 1 WHERE id = ?", (track_id,)
        )
        row = conn.execute(
            "SELECT play_count, path FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
    return (row["play_count"], row["path"]) if row else (0, None)


def set_play_count(track_id: int, count: int):
    with db() as conn:
        conn.execute(
            "UPDATE tracks SET play_count = ? WHERE id = ?", (count, track_id)
        )


def get_setting(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))


def del_setting(key: str):
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))


def get_cover(hash_: str):
    with db() as conn:
        row = conn.execute(
            "SELECT data, mime FROM covers WHERE hash = ?", (hash_,)
        ).fetchone()
    return (row["data"], row["mime"]) if row else (None, None)


# ── Per-user play counts ──────────────────────────────────────────────────────

def increment_user_play_count(user_id: int, track_id: int):
    """Increment play count for a specific user (0 = Adolar Disco)."""
    now = __import__("time").time()
    with db() as conn:
        conn.execute("""
            INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id, track_id) DO UPDATE SET
                count = count + 1,
                last_played_at = excluded.last_played_at
        """, (user_id, track_id, now))


# ── Playlists ─────────────────────────────────────────────────────────────────

def get_playlists(user_id: int) -> list[dict]:
    """Return system playlists + playlists owned by user_id."""
    with db() as conn:
        rows = conn.execute(
            """SELECT p.id, p.owner_id, p.name, p.type, p.filters, p.sort,
                      p.is_system, p.created_at,
                      (SELECT COUNT(*) FROM playlist_tracks pt WHERE pt.playlist_id=p.id) AS track_count
               FROM playlists p
               WHERE p.is_system=1 OR p.owner_id=?
               ORDER BY p.is_system DESC, p.type ASC, p.created_at ASC""",
            (user_id,)
        ).fetchall()
    return [dict(r) for r in rows]


def create_playlist(user_id: int, name: str, filters: str, sort: str,
                    type_: str = "smart") -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO playlists (owner_id, name, type, filters, sort) VALUES (?,?,?,?,?)",
            (user_id, name, type_, filters, sort)
        )
        return cur.lastrowid


def get_or_create_radio_favorites(user_id: int) -> int:
    """Return playlist id of user's radio bookmark playlist, creating it if needed."""
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM playlists WHERE owner_id=? AND type='static' AND name='Adolar Radio Favoriten'",
            (user_id,)
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO playlists (owner_id, name, type, filters, sort) VALUES (?,?,?,?,?)",
            (user_id, "Adolar Radio Favoriten", "static", "{}", "artist")
        )
        return cur.lastrowid


def get_track_playlist_memberships(user_id: int, track_ids: list[int]) -> dict[int, list[int]]:
    """Returns {track_id: [playlist_id, ...]} for all personal playlists of user."""
    if not track_ids:
        return {}
    placeholders = ",".join("?" * len(track_ids))
    with db() as conn:
        rows = conn.execute(
            f"""SELECT pt.track_id, pt.playlist_id
                FROM playlist_tracks pt
                JOIN playlists p ON p.id = pt.playlist_id
                WHERE p.owner_id = ? AND pt.track_id IN ({placeholders})""",
            [user_id] + list(track_ids)
        ).fetchall()
    result: dict[int, list[int]] = {}
    for r in rows:
        result.setdefault(r["track_id"], []).append(r["playlist_id"])
    return result


def add_track_to_playlist(playlist_id: int, track_id: int):
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id) VALUES (?,?)",
            (playlist_id, track_id)
        )


def get_playlist_tracks(playlist_id: int, user_id: int) -> list[dict] | None:
    """Returns track list for a static playlist owned by user_id, or None if not found/wrong owner."""
    with db() as conn:
        pl = conn.execute(
            "SELECT id, owner_id, type FROM playlists WHERE id=?", (playlist_id,)
        ).fetchone()
        if not pl or (pl["owner_id"] is not None and pl["owner_id"] != user_id):
            return None
        rows = conn.execute(
            """SELECT t.id, t.path, t.title, t.artist, t.album, t.genre,
                      t.year, t.duration, t.bitrate, t.cover_hash, t.bpm
               FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
               WHERE pt.playlist_id = ?
               ORDER BY pt.added_at""",
            (playlist_id,)
        ).fetchall()
    import os as _os

    def _fmt(s):
        if not s: return "0:00"
        m, sec = divmod(int(s), 60); return f"{m}:{sec:02d}"

    tracks = []
    for r in rows:
        d = dict(r)
        d["duration_fmt"] = _fmt(d["duration"])
        d["format"] = _os.path.splitext(d["path"])[1].lstrip(".").upper() if d.get("path") else "MP3"
        d["has_cover"] = bool(d["cover_hash"])
        d["loved"] = False
        tracks.append(d)
    return tracks


def delete_playlist(playlist_id: int, user_id: int) -> bool:
    """Only owner can delete; system playlists cannot be deleted."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM playlists WHERE id=? AND owner_id=? AND is_system=0",
            (playlist_id, user_id)
        )
    return cur.rowcount > 0


def rename_playlist(playlist_id: int, user_id: int, name: str) -> bool:
    with db() as conn:
        cur = conn.execute(
            "UPDATE playlists SET name=? WHERE id=? AND owner_id=? AND is_system=0",
            (name, playlist_id, user_id)
        )
    return cur.rowcount > 0
