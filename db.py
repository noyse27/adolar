import sqlite3
import os
import json
from contextlib import contextmanager
import smart_shuffle
import adolar4u

DB_PATH = os.environ.get("DB_PATH", "/data/adolar.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA mmap_size=134217728")
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
        # Set the persistent journal mode once instead of repeating it on every request.
        conn.execute("PRAGMA journal_mode=WAL")
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
                play_count_tag_dirty INTEGER NOT NULL DEFAULT 0,
                loved       INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS users (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                username             TEXT    NOT NULL UNIQUE,
                password_hash        TEXT    NOT NULL,
                role                 TEXT    NOT NULL DEFAULT 'user',
                allow_download       INTEGER NOT NULL DEFAULT 0,
                allow_playlists      INTEGER NOT NULL DEFAULT 1,
                allow_radio_stations INTEGER NOT NULL DEFAULT 1,
                contributes_playcount INTEGER NOT NULL DEFAULT 0,
                is_active            INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 1,
                created_at           TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS user_lastfm_accounts (
                user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                username      TEXT NOT NULL,
                session_key   TEXT NOT NULL,
                auto_love_favorites INTEGER NOT NULL DEFAULT 1,
                connected_at  REAL NOT NULL DEFAULT (unixepoch()),
                loved_synced_at REAL,
                playcounts_synced_at REAL
            );

            CREATE TABLE IF NOT EXISTS lastfm_loved_tracks (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                artist_norm TEXT NOT NULL,
                title_norm  TEXT NOT NULL,
                artist      TEXT,
                title       TEXT,
                loved_at    INTEGER,
                synced_at   REAL DEFAULT (unixepoch()),
                PRIMARY KEY (user_id, artist_norm, title_norm)
            );

            CREATE TABLE IF NOT EXISTS user_lastfm_sync_jobs (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                job_type    TEXT NOT NULL CHECK(job_type IN ('loved','playcounts')),
                running     INTEGER NOT NULL DEFAULT 0,
                error       TEXT,
                done        INTEGER NOT NULL DEFAULT 0,
                total       INTEGER NOT NULL DEFAULT 0,
                result_count INTEGER NOT NULL DEFAULT 0,
                updated_count INTEGER NOT NULL DEFAULT 0,
                finished_at REAL,
                PRIMARY KEY (user_id, job_type)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at REAL    NOT NULL,
                connection_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS connection_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
                username     TEXT    NOT NULL,
                product      TEXT    NOT NULL,
                ip_address   TEXT    NOT NULL,
                connected_at REAL    NOT NULL,
                last_seen_at REAL    NOT NULL,
                client_key   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_connection_log_connected
            ON connection_log(connected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_connection_log_active
            ON connection_log(last_seen_at DESC);

            CREATE TABLE IF NOT EXISTS login_blocks (
                ip           TEXT PRIMARY KEY,
                blocked_until REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id   INTEGER REFERENCES users(id) ON DELETE SET NULL,
                action     TEXT NOT NULL,
                target     TEXT,
                details    TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);

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
                system_key TEXT,
                created_at TEXT    DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                added_at    REAL    DEFAULT (unixepoch()),
                PRIMARY KEY (playlist_id, track_id)
            );
            CREATE INDEX IF NOT EXISTS idx_plt_playlist ON playlist_tracks(playlist_id, added_at);

            CREATE TABLE IF NOT EXISTS radio_stations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                description TEXT    NOT NULL DEFAULT '',
                filter_json TEXT    NOT NULL DEFAULT '{"mode":"all","rules":[]}',
                scope       TEXT    NOT NULL DEFAULT 'global',
                owner_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
                jingle_path TEXT,
                jingle_every_tracks INTEGER NOT NULL DEFAULT 0,
                jingle_enabled INTEGER NOT NULL DEFAULT 0,
                is_system   INTEGER NOT NULL DEFAULT 0,
                created_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at  TEXT    DEFAULT (datetime('now')),
                updated_at  TEXT    DEFAULT (datetime('now')),
                engine      TEXT    NOT NULL DEFAULT 'smart_shuffle',
                UNIQUE(scope, owner_id, name)
            );
        """)
        # Seed system playlists (idempotent)
        _seed_system_playlists(conn)
        # Migrations (safe to run repeatedly)
        for migration in [
            "ALTER TABLE tracks ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tracks ADD COLUMN bpm REAL",
            "ALTER TABLE tracks ADD COLUMN play_count_tag_dirty INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE tracks ADD COLUMN loved INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN contributes_playcount INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE radio_stations ADD COLUMN description TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE radio_stations ADD COLUMN scope TEXT NOT NULL DEFAULT 'global'",
            "ALTER TABLE radio_stations ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE",
            "ALTER TABLE radio_stations ADD COLUMN jingle_path TEXT",
            "ALTER TABLE radio_stations ADD COLUMN jingle_every_tracks INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE radio_stations ADD COLUMN jingle_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE radio_stations ADD COLUMN created_by INTEGER REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE radio_stations ADD COLUMN updated_at TEXT",
            "ALTER TABLE radio_stations ADD COLUMN engine TEXT NOT NULL DEFAULT 'smart_shuffle'",
            "ALTER TABLE users ADD COLUMN allow_playlists INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN allow_radio_stations INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE playlists ADD COLUMN system_key TEXT",
            "ALTER TABLE sessions ADD COLUMN connection_id INTEGER",
            "ALTER TABLE connection_log ADD COLUMN client_key TEXT",
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_connection_log_client
            ON connection_log(client_key) WHERE client_key IS NOT NULL
        """)
        _migrate_lastfm_schema(conn)
        _migrate_personal_favorites(conn)
        _seed_radio_stations(conn)
        adolar4u.init_schema(conn)
        # Play-count/BPM updates must not churn the full-text index.
        conn.executescript("""
            DROP TRIGGER IF EXISTS tracks_au;
            CREATE TRIGGER tracks_au
            AFTER UPDATE OF title, artist, album, genre ON tracks BEGIN
                INSERT INTO tracks_fts(tracks_fts, rowid, title, artist, album, genre)
                VALUES ('delete', old.id, old.title, old.artist, old.album, old.genre);
                INSERT INTO tracks_fts(rowid, title, artist, album, genre)
                VALUES (new.id, new.title, new.artist, new.album, new.genre);
            END;
        """)
        queued = conn.execute("""
            INSERT OR IGNORE INTO settings (key, value)
            VALUES ('migration:queue_existing_play_counts', datetime('now'))
        """)
        if queued.rowcount:
            conn.execute("""
                UPDATE tracks SET play_count_tag_dirty=1
                WHERE play_count > 0
            """)


_SYSTEM_PLAYLISTS = [
    ("Zuletzt gespielt",    "recent",       "{}"),
    ("Meistgespielt",       "top_played",   "{}"),
    ("Neueste 100",         "newest_added", "{}"),
    ("Disco Hits",          "disco_top",    "{}"),
]


def _table_columns(conn, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_lastfm_schema(conn) -> None:
    """Move the former global Last.fm account and loved rows to its admin owner."""
    columns = _table_columns(conn, "lastfm_loved_tracks")
    if columns and "user_id" not in columns:
        conn.execute("ALTER TABLE lastfm_loved_tracks RENAME TO lastfm_loved_tracks_legacy")
        conn.executescript("""
            CREATE TABLE lastfm_loved_tracks (
                user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                artist_norm TEXT NOT NULL,
                title_norm  TEXT NOT NULL,
                artist      TEXT,
                title       TEXT,
                loved_at    INTEGER,
                synced_at   REAL DEFAULT (unixepoch()),
                PRIMARY KEY (user_id, artist_norm, title_norm)
            );
        """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lastfm_loved_user
        ON lastfm_loved_tracks(user_id, loved_at DESC)
    """)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_lastfm_accounts (
            user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            username      TEXT NOT NULL,
            session_key   TEXT NOT NULL,
            auto_love_favorites INTEGER NOT NULL DEFAULT 1,
            connected_at  REAL NOT NULL DEFAULT (unixepoch()),
            loved_synced_at REAL,
            playcounts_synced_at REAL
        );
        CREATE TABLE IF NOT EXISTS user_lastfm_sync_jobs (
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_type    TEXT NOT NULL CHECK(job_type IN ('loved','playcounts')),
            running     INTEGER NOT NULL DEFAULT 0,
            error       TEXT,
            done        INTEGER NOT NULL DEFAULT 0,
            total       INTEGER NOT NULL DEFAULT 0,
            result_count INTEGER NOT NULL DEFAULT 0,
            updated_count INTEGER NOT NULL DEFAULT 0,
            finished_at REAL,
            PRIMARY KEY (user_id, job_type)
        );
    """)
    legacy_username = conn.execute(
        "SELECT value FROM settings WHERE key='lastfm_username'"
    ).fetchone()
    legacy_key = conn.execute(
        "SELECT value FROM settings WHERE key='lastfm_session_key'"
    ).fetchone()
    admin = conn.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if admin:
        user_id = int(admin["id"])
        if "lastfm_loved_tracks_legacy" in {
            row["name"] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }:
            conn.execute("""
                INSERT OR IGNORE INTO lastfm_loved_tracks
                    (user_id, artist_norm, title_norm, artist, title, loved_at, synced_at)
                SELECT ?, artist_norm, title_norm, artist, title, loved_at, synced_at
                FROM lastfm_loved_tracks_legacy
            """, (user_id,))
            conn.execute("DROP TABLE lastfm_loved_tracks_legacy")
    if legacy_username and legacy_key and admin:
        conn.execute("""
            INSERT OR IGNORE INTO user_lastfm_accounts
                (user_id, username, session_key, auto_love_favorites)
            VALUES (?, ?, ?, 1)
        """, (user_id, legacy_username["value"], legacy_key["value"]))
        conn.execute(
            "DELETE FROM settings WHERE key IN ('lastfm_username','lastfm_session_key','lastfm_loved_synced_at')"
        )


def _migrate_personal_favorites(conn) -> None:
    """Turn the former radio bookmark list into one protected Favorites list."""
    if "system_key" not in _table_columns(conn, "playlists"):
        return
    owners = conn.execute("""
        SELECT DISTINCT owner_id FROM playlists
        WHERE owner_id IS NOT NULL AND name IN ('Adolar Radio Favoriten', 'Favoriten')
    """).fetchall()
    for owner in owners:
        user_id = int(owner["owner_id"])
        rows = conn.execute("""
            SELECT id, name FROM playlists
            WHERE owner_id=? AND name IN ('Adolar Radio Favoriten', 'Favoriten')
            ORDER BY CASE name WHEN 'Favoriten' THEN 0 ELSE 1 END, id
        """, (user_id,)).fetchall()
        target_id = int(rows[0]["id"])
        for duplicate in rows[1:]:
            conn.execute("""
                INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id, added_at)
                SELECT ?, track_id, added_at FROM playlist_tracks WHERE playlist_id=?
            """, (target_id, int(duplicate["id"])))
            conn.execute("DELETE FROM playlists WHERE id=?", (int(duplicate["id"]),))
        conn.execute("""
            UPDATE playlists
            SET name='Favoriten', type='static', filters='{}', sort='artist',
                is_system=1, system_key='favorites'
            WHERE id=?
        """, (target_id,))
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_playlists_personal_system
        ON playlists(owner_id, system_key)
        WHERE owner_id IS NOT NULL AND system_key IS NOT NULL
    """)
    conn.execute("""
        INSERT OR IGNORE INTO playlists
            (owner_id, name, type, filters, sort, is_system, system_key)
        SELECT id, 'Favoriten', 'static', '{}', 'artist', 1, 'favorites'
        FROM users
    """)

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


def _seed_radio_stations(conn):
    conn.execute("""
        INSERT OR IGNORE INTO radio_stations
            (id, name, description, filter_json, scope, owner_id, jingle_every_tracks,
             jingle_enabled, is_system, created_by)
        VALUES
            (1, 'Adolar Radio', 'Alle Tracks in zufälliger Reihenfolge',
             '{"mode":"all","rules":[]}', 'global', NULL, 0, 0, 1, NULL)
    """)
    conn.execute("""
        DELETE FROM radio_stations
        WHERE engine='adolar4u' AND id NOT IN (
            SELECT MIN(id) FROM radio_stations WHERE engine='adolar4u'
        )
    """)
    conn.execute("""
        INSERT INTO radio_stations
            (name, description, filter_json, scope, owner_id, jingle_every_tracks,
             jingle_enabled, is_system, created_by, engine)
        SELECT
            'Adolar4U', 'Persönlicher, lernender Radiosender',
            '{"mode":"all","rules":[]}', 'global', NULL, 0, 0, 1, NULL,
            'adolar4u'
        WHERE NOT EXISTS (
            SELECT 1 FROM radio_stations WHERE engine='adolar4u'
        )
    """)


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
                  user_id=None, random_order=False):
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
    if (loved_only or include_loved or sort == "loved_at") and user_id:
        loved_uid = int(user_id)
        loved_join = """LEFT JOIN lastfm_loved_tracks l
                  ON l.artist_norm = LOWER(COALESCE(t.artist, ''))
                 AND l.title_norm = LOWER(COALESCE(t.title, ''))
                 AND l.user_id = %d""" % loved_uid
        loved_select = "CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved, l.loved_at"
    if loved_only:
        conditions.append("l.artist_norm IS NOT NULL" if user_id else "0=1")

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

    if random_order:
        order = "RANDOM()"

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


def get_lastfm_account(user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("""
            SELECT user_id, username, session_key, auto_love_favorites,
                   connected_at, loved_synced_at, playcounts_synced_at
            FROM user_lastfm_accounts WHERE user_id=?
        """, (int(user_id),)).fetchone()
    return dict(row) if row else None


def set_lastfm_account(user_id: int, username: str, session_key: str) -> None:
    with db() as conn:
        conn.execute("""
            INSERT INTO user_lastfm_accounts (user_id, username, session_key)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                session_key=excluded.session_key,
                connected_at=unixepoch()
        """, (int(user_id), username, session_key))


def disconnect_lastfm_account(user_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM user_lastfm_sync_jobs WHERE user_id=?", (int(user_id),))
        conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (int(user_id),))
        conn.execute("DELETE FROM user_lastfm_accounts WHERE user_id=?", (int(user_id),))


def set_lastfm_auto_love(user_id: int, enabled: bool) -> bool:
    with db() as conn:
        cur = conn.execute("""
            UPDATE user_lastfm_accounts SET auto_love_favorites=? WHERE user_id=?
        """, (1 if enabled else 0, int(user_id)))
    return cur.rowcount > 0


_LASTFM_SYNC_FIELDS = {
    "running", "error", "done", "total", "result_count", "updated_count",
    "finished_at",
}


def get_lastfm_sync_state(user_id: int, job_type: str) -> dict:
    if job_type not in ("loved", "playcounts"):
        raise ValueError("invalid Last.fm sync job type")
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO user_lastfm_sync_jobs (user_id, job_type)
            VALUES (?, ?)
        """, (int(user_id), job_type))
        row = conn.execute("""
            SELECT running, error, done, total, result_count, updated_count,
                   finished_at
            FROM user_lastfm_sync_jobs WHERE user_id=? AND job_type=?
        """, (int(user_id), job_type)).fetchone()
    result = dict(row)
    result["running"] = bool(result["running"])
    if job_type == "loved":
        result["count"] = result.pop("result_count")
        result.pop("updated_count", None)
    else:
        result["updated"] = result.pop("updated_count")
        result.pop("result_count", None)
    return result


def update_lastfm_sync_state(user_id: int, job_type: str, **values) -> dict:
    invalid = set(values) - _LASTFM_SYNC_FIELDS
    if invalid or job_type not in ("loved", "playcounts"):
        raise ValueError("invalid Last.fm sync state")
    mapped = dict(values)
    if "running" in mapped:
        mapped["running"] = 1 if mapped["running"] else 0
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO user_lastfm_sync_jobs (user_id, job_type)
            VALUES (?, ?)
        """, (int(user_id), job_type))
        if mapped:
            assignments = ", ".join(f"{field}=?" for field in mapped)
            conn.execute(
                f"UPDATE user_lastfm_sync_jobs SET {assignments} WHERE user_id=? AND job_type=?",
                [*mapped.values(), int(user_id), job_type],
            )
    return get_lastfm_sync_state(user_id, job_type)


def claim_lastfm_sync_job(user_id: int, job_type: str) -> bool:
    if job_type not in ("loved", "playcounts"):
        raise ValueError("invalid Last.fm sync job type")
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO user_lastfm_sync_jobs (user_id, job_type)
            VALUES (?, ?)
        """, (int(user_id), job_type))
        cur = conn.execute("""
            UPDATE user_lastfm_sync_jobs
            SET running=1, error=NULL, done=0, total=0,
                result_count=0, updated_count=0, finished_at=NULL
            WHERE user_id=? AND job_type=? AND running=0
        """, (int(user_id), job_type))
    return cur.rowcount > 0


def replace_lastfm_loved_tracks(user_id: int, items: list[dict]):
    now = __import__("time").time()
    rows = [
        (
            int(user_id), _norm_text(item.get("artist")),
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
        conn.execute("DELETE FROM lastfm_loved_tracks WHERE user_id=?", (int(user_id),))
        conn.executemany(
            """INSERT OR REPLACE INTO lastfm_loved_tracks
               (user_id, artist_norm, title_norm, artist, title, loved_at, synced_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.execute(
            "UPDATE user_lastfm_accounts SET loved_synced_at=? WHERE user_id=?",
            (now, int(user_id)),
        )
    return len(rows)


def set_lastfm_loved(user_id: int, artist: str, title: str, loved: bool):
    artist_norm = _norm_text(artist)
    title_norm = _norm_text(title)
    if not artist_norm or not title_norm:
        return
    with db() as conn:
        if loved:
            conn.execute(
                """INSERT OR REPLACE INTO lastfm_loved_tracks
                   (user_id, artist_norm, title_norm, artist, title, loved_at, synced_at)
                   VALUES (?, ?, ?, ?, ?, unixepoch(), unixepoch())""",
                (int(user_id), artist_norm, title_norm, artist, title),
            )
        else:
            conn.execute(
                "DELETE FROM lastfm_loved_tracks WHERE user_id=? AND artist_norm=? AND title_norm=?",
                (int(user_id), artist_norm, title_norm),
            )


def get_lastfm_loved_status(user_id: int):
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM lastfm_loved_tracks WHERE user_id=?", (int(user_id),)
        ).fetchone()[0]
        row = conn.execute(
            "SELECT loved_synced_at FROM user_lastfm_accounts WHERE user_id=?", (int(user_id),)
        ).fetchone()
    return {"total": total, "synced_at": row["loved_synced_at"] if row else None}


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


def get_random_tracks(count=25, exclude_ids=None, shuffle_state=None):
    count = max(1, min(int(count), 100))
    excl = [int(x) for x in (exclude_ids or [])]
    with db() as conn:
        if shuffle_state is None:
            shuffle_state = smart_shuffle.ShuffleState(context="random")
        if shuffle_state.total_tracks is None:
            stats = conn.execute("""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT LOWER(TRIM(artist))) AS artists,
                       COUNT(DISTINCT CASE WHEN TRIM(album) != '' THEN
                           COALESCE(LOWER(TRIM(artist)), '') || CHAR(31) ||
                           LOWER(TRIM(album)) END) AS albums,
                       COUNT(DISTINCT CASE WHEN TRIM(genre) != '' THEN
                           LOWER(TRIM(genre)) END) AS genres
                FROM tracks
            """).fetchone()
            shuffle_state.total_tracks = stats["total"]
            shuffle_state.unique_artists = stats["artists"]
            shuffle_state.unique_albums = stats["albums"]
            shuffle_state.unique_genres = stats["genres"]
        pool_size = min(
            shuffle_state.total_tracks,
            max(2500, count * 100),
        )
        rows = conn.execute(
            """SELECT id, path, title, artist, album, genre, year, track_no,
                       duration, bitrate, size, cover_hash, bpm
                FROM tracks
                ORDER BY RANDOM() LIMIT ?""",
            (pool_size,),
        ).fetchall()
    selected = smart_shuffle.select_tracks(
        rows, count, shuffle_state,
        shuffle_state.total_tracks,
        shuffle_state.unique_artists,
        shuffle_state.unique_albums,
        exclude_ids=excl,
        unique_genres=shuffle_state.unique_genres or 0,
    )
    return _track_rows_to_dicts(selected)


# ── Radio stations ───────────────────────────────────────────────────────────

_RADIO_TEXT_FIELDS = {
    "title": "t.title",
    "artist": "t.artist",
    "album": "t.album",
    "genre": "t.genre",
}
_RADIO_NUM_FIELDS = {
    "year": "t.year",
    "decade": "t.year",
    "playcount": "COALESCE(upc.count, 0)",
}


def _track_rows_to_dicts(rows) -> list[dict]:
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
        d["user_play_count"] = d.get("user_play_count", 0)
        tracks.append(d)
    return tracks


def _normalize_radio_filter(filter_def) -> dict:
    if not isinstance(filter_def, dict):
        return {"mode": "all", "rules": []}
    mode = filter_def.get("mode")
    if mode not in ("all", "any"):
        mode = "all"
    rules = filter_def.get("rules")
    if not isinstance(rules, list):
        rules = []
    return {"mode": mode, "rules": rules[:50]}


def validate_radio_filter(filter_def) -> dict:
    """Return a normalized filter tree or raise ValueError."""
    def walk(node, depth=0):
        if depth > 4:
            raise ValueError("filter too deeply nested")
        node = _normalize_radio_filter(node)
        out = {"mode": node["mode"], "rules": []}
        for rule in node["rules"]:
            if not isinstance(rule, dict):
                continue
            if "rules" in rule:
                child = walk(rule, depth + 1)
                if child["rules"]:
                    out["rules"].append(child)
                continue
            field = rule.get("field")
            op = rule.get("op")
            value = rule.get("value")
            if field in _RADIO_TEXT_FIELDS:
                if op not in ("contains", "not_contains"):
                    raise ValueError(f"invalid operator for {field}")
                value = str(value or "").strip()
                if value:
                    out["rules"].append({"field": field, "op": op, "value": value[:120]})
            elif field in _RADIO_NUM_FIELDS:
                if op not in ("eq", "ne", "gt", "lt"):
                    raise ValueError(f"invalid operator for {field}")
                try:
                    num = int(value)
                except (TypeError, ValueError):
                    raise ValueError(f"invalid numeric value for {field}")
                if field == "decade":
                    num = (num // 10) * 10
                out["rules"].append({"field": field, "op": op, "value": num})
            else:
                raise ValueError("invalid filter field")
        return out
    return walk(filter_def)


def _radio_filter_uses_genre(filter_def) -> bool:
    """Return whether any nested radio rule explicitly targets genre."""
    if not isinstance(filter_def, dict):
        return False
    for rule in filter_def.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("field") == "genre" or _radio_filter_uses_genre(rule):
            return True
    return False


def _radio_filter_sql(filter_def) -> tuple[str, list]:
    filter_def = validate_radio_filter(filter_def)

    def walk(node) -> tuple[str, list]:
        parts = []
        params = []
        for rule in node["rules"]:
            if "rules" in rule:
                sql, child_params = walk(rule)
                if sql:
                    parts.append(f"({sql})")
                    params.extend(child_params)
                continue
            field, op, value = rule["field"], rule["op"], rule["value"]
            if field in _RADIO_TEXT_FIELDS:
                col = _RADIO_TEXT_FIELDS[field]
                expr = f"LOWER(COALESCE({col}, '')) LIKE ? ESCAPE '\\'"
                if op == "not_contains":
                    expr = f"NOT ({expr})"
                parts.append(expr)
                params.append(_like_pattern(str(value).casefold()))
            elif field == "decade":
                start, end = int(value), int(value) + 9
                if op == "eq":
                    parts.append("(t.year >= ? AND t.year <= ?)")
                    params.extend([start, end])
                elif op == "ne":
                    parts.append("(t.year IS NULL OR t.year < ? OR t.year > ?)")
                    params.extend([start, end])
                elif op == "gt":
                    parts.append("t.year > ?")
                    params.append(end)
                elif op == "lt":
                    parts.append("t.year < ?")
                    params.append(start)
            else:
                col = _RADIO_NUM_FIELDS[field]
                sql_op = {"eq": "=", "ne": "!=", "gt": ">", "lt": "<"}[op]
                if op == "ne":
                    parts.append(f"({col} IS NULL OR {col} {sql_op} ?)")
                else:
                    parts.append(f"{col} {sql_op} ?")
                params.append(int(value))
        joiner = " AND " if node["mode"] == "all" else " OR "
        return joiner.join(parts), params

    return walk(filter_def)


def _radio_station_from_row(row) -> dict:
    d = dict(row)
    d["is_system"] = bool(d["is_system"])
    d["jingle_enabled"] = bool(d.get("jingle_enabled"))
    d["has_jingle"] = bool(d.pop("jingle_path", None))
    d["scope"] = d.get("scope") or "global"
    d["engine"] = d.get("engine") or "smart_shuffle"
    try:
        d["filter"] = json.loads(d.pop("filter_json") or "{}")
    except Exception:
        d["filter"] = {"mode": "all", "rules": []}
    return d


def list_radio_stations(user_id: int | None = None, include_all_private: bool = False) -> list[dict]:
    with db() as conn:
        _seed_radio_stations(conn)
        params = []
        where = ["rs.scope='global'"]
        if user_id:
            where.append("(rs.scope='private' AND rs.owner_id=?)")
            params.append(user_id)
        if include_all_private:
            where.append("rs.scope='private'")
        rows = conn.execute("""
            SELECT rs.id, rs.name, rs.description, rs.filter_json, rs.scope,
                   rs.owner_id, u.username AS owner_name, rs.jingle_path,
                   rs.jingle_every_tracks, rs.jingle_enabled, rs.is_system, rs.created_by,
                   rs.created_at, rs.updated_at, rs.engine
            FROM radio_stations rs
            LEFT JOIN users u ON u.id=rs.owner_id
            WHERE """ + " OR ".join(where) + """
            GROUP BY rs.id
            ORDER BY rs.is_system DESC,
                     CASE rs.engine WHEN 'adolar4u' THEN 1 ELSE 0 END,
                     CASE rs.scope WHEN 'global' THEN 0 ELSE 1 END,
                     u.username COLLATE NOCASE,
                     rs.name COLLATE NOCASE
        """, params).fetchall()
    return [_radio_station_from_row(r) for r in rows]


def get_radio_station(station_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("""
            SELECT rs.id, rs.name, rs.description, rs.filter_json, rs.scope,
                   rs.owner_id, u.username AS owner_name, rs.jingle_path,
                   rs.jingle_every_tracks, rs.jingle_enabled, rs.is_system, rs.created_by,
                   rs.created_at, rs.updated_at, rs.engine
            FROM radio_stations rs
            LEFT JOIN users u ON u.id=rs.owner_id
            WHERE rs.id=?
        """, (station_id,)).fetchone()
    if not row:
        return None
    return _radio_station_from_row(row)


def create_radio_station(name: str, description: str, filter_def: dict,
                         user_id: int, scope: str = "private") -> int:
    clean = validate_radio_filter(filter_def)
    scope = scope if scope in ("global", "private") else "private"
    owner_id = None if scope == "global" else int(user_id)
    with db() as conn:
        existing = conn.execute("""
            SELECT 1 FROM radio_stations
            WHERE scope=? AND COALESCE(owner_id, 0)=COALESCE(?, 0)
              AND LOWER(name)=LOWER(?)
        """, (scope, owner_id, name.strip())).fetchone()
        if existing:
            raise sqlite3.IntegrityError("UNIQUE radio station name")
        cur = conn.execute("""
            INSERT INTO radio_stations
                (name, description, filter_json, scope, owner_id, is_system, created_by, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, datetime('now'))
        """, (name.strip(), (description or "").strip(), json.dumps(clean, ensure_ascii=False),
              scope, owner_id, user_id))
        return cur.lastrowid


def update_radio_station(station_id: int, name: str, description: str, filter_def: dict,
                         user_id: int, is_admin: bool, scope: str | None = None) -> bool:
    clean = validate_radio_filter(filter_def)
    station = get_radio_station(station_id)
    if not station or station["is_system"]:
        return False
    if not is_admin and station.get("owner_id") != user_id:
        return False
    if not is_admin and station.get("scope") != "private":
        return False
    new_scope = station["scope"]
    owner_id = station.get("owner_id")
    if is_admin and scope in ("global", "private"):
        new_scope = scope
        owner_id = None if new_scope == "global" else (owner_id or user_id)
    with db() as conn:
        existing = conn.execute("""
            SELECT 1 FROM radio_stations
            WHERE id<>? AND scope=? AND COALESCE(owner_id, 0)=COALESCE(?, 0)
              AND LOWER(name)=LOWER(?)
        """, (station_id, new_scope, owner_id, name.strip())).fetchone()
        if existing:
            raise sqlite3.IntegrityError("UNIQUE radio station name")
        cur = conn.execute("""
            UPDATE radio_stations
            SET name=?, description=?, filter_json=?, scope=?, owner_id=?, updated_at=datetime('now')
            WHERE id=? AND is_system=0
        """, (name.strip(), (description or "").strip(), json.dumps(clean, ensure_ascii=False),
              new_scope, owner_id, station_id))
        return cur.rowcount > 0


def delete_radio_station(station_id: int, user_id: int, is_admin: bool) -> bool:
    station = get_radio_station(station_id)
    if not station or station["is_system"]:
        return False
    if not is_admin and station.get("owner_id") != user_id:
        return False
    with db() as conn:
        cur = conn.execute("DELETE FROM radio_stations WHERE id=? AND is_system=0", (station_id,))
        return cur.rowcount > 0


def can_manage_radio_station(station_id: int, user_id: int, is_admin: bool) -> bool:
    station = get_radio_station(station_id)
    if not station:
        return False
    if station["is_system"]:
        return bool(is_admin)
    return bool(is_admin or station.get("owner_id") == user_id)


def set_radio_station_jingle(station_id: int, path: str | None,
                             every_tracks: int, enabled: bool) -> bool:
    every_tracks = max(0, int(every_tracks or 0))
    with db() as conn:
        cur = conn.execute("""
            UPDATE radio_stations
            SET jingle_path=?, jingle_every_tracks=?, jingle_enabled=?, updated_at=datetime('now')
            WHERE id=?
        """, (path, every_tracks, 1 if enabled and path and every_tracks > 0 else 0, station_id))
        return cur.rowcount > 0


def update_radio_station_jingle_settings(station_id: int, every_tracks: int, enabled: bool) -> bool:
    every_tracks = max(0, int(every_tracks or 0))
    with db() as conn:
        cur = conn.execute("""
            UPDATE radio_stations
            SET jingle_every_tracks=?,
                jingle_enabled=CASE WHEN jingle_path IS NOT NULL AND ?>0 THEN ? ELSE 0 END,
                updated_at=datetime('now')
            WHERE id=?
        """, (every_tracks, every_tracks, 1 if enabled else 0, station_id))
        return cur.rowcount > 0


def get_radio_station_jingle_path(station_id: int, enabled_only: bool = True) -> str | None:
    where = "id=? AND jingle_enabled=1" if enabled_only else "id=?"
    with db() as conn:
        row = conn.execute(
            f"SELECT jingle_path FROM radio_stations WHERE {where}",
            (station_id,),
        ).fetchone()
    return row["jingle_path"] if row and row["jingle_path"] else None


def get_radio_station_tracks(station_id: int, count=25, exclude_ids=None, user_id=None,
                             shuffle_state=None,
                             recommendation_session_id: str | None = None) -> list[dict] | None:
    station = get_radio_station(station_id)
    if not station:
        return None
    if station.get("engine") == "adolar4u":
        if not user_id:
            return None
        return adolar4u.recommend_tracks(
            int(user_id), count=count, exclude_ids=exclude_ids,
            shuffle_state=shuffle_state,
            recommendation_session_id=recommendation_session_id,
        )
    return get_radio_filter_tracks(
        station.get("filter") or {}, count, exclude_ids,
        user_id=user_id, shuffle_state=shuffle_state,
    )


def get_radio_filter_tracks(filter_def: dict, count=25, exclude_ids=None, user_id=None,
                            shuffle_state=None) -> list[dict]:
    count = max(1, min(int(count), 100))
    excl = [int(x) for x in (exclude_ids or []) if str(x).isdigit()]
    where_sql, params = _radio_filter_sql(filter_def or {})
    conditions = []
    if where_sql:
        conditions.append(f"({where_sql})")
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    uid = int(user_id or 0)
    with db() as conn:
        if shuffle_state is None:
            shuffle_state = smart_shuffle.ShuffleState(context="radio-filter")
        if shuffle_state.total_tracks is None:
            stats = conn.execute(f"""
                SELECT COUNT(*) AS total,
                       COUNT(DISTINCT LOWER(TRIM(t.artist))) AS artists,
                       COUNT(DISTINCT CASE WHEN TRIM(t.album) != '' THEN
                           COALESCE(LOWER(TRIM(t.artist)), '') || CHAR(31) ||
                           LOWER(TRIM(t.album)) END) AS albums,
                       COUNT(DISTINCT CASE WHEN TRIM(t.genre) != '' THEN
                           LOWER(TRIM(t.genre)) END) AS genres
                FROM tracks t
                LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id=?
                {where}
            """, [uid] + params).fetchone()
            shuffle_state.total_tracks = stats["total"]
            shuffle_state.unique_artists = stats["artists"]
            shuffle_state.unique_albums = stats["albums"]
            shuffle_state.unique_genres = stats["genres"]
        pool_size = min(
            shuffle_state.total_tracks,
            max(2500, count * 100),
        )
        rows = conn.execute(f"""
            SELECT t.id, t.path, t.title, t.artist, t.album, t.genre, t.year, t.track_no,
                   t.duration, t.bitrate, t.size, t.cover_hash, t.bpm,
                   COALESCE(upc.count, 0) AS user_play_count, upc.last_played_at,
                   CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved
            FROM tracks t
            LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id=?
            LEFT JOIN lastfm_loved_tracks l
                   ON l.artist_norm=LOWER(COALESCE(t.artist, ''))
                  AND l.title_norm=LOWER(COALESCE(t.title, ''))
                  AND l.user_id=?
            {where}
            ORDER BY RANDOM()
            LIMIT ?
        """, [uid, uid] + params + [pool_size]).fetchall()
    selected = smart_shuffle.select_tracks(
        rows, count, shuffle_state,
        shuffle_state.total_tracks,
        shuffle_state.unique_artists,
        shuffle_state.unique_albums,
        exclude_ids=excl,
        unique_genres=shuffle_state.unique_genres or 0,
        use_genre_spacing=not _radio_filter_uses_genre(filter_def),
    )
    return _track_rows_to_dicts(selected)


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


def record_user_play(user_id: int, track_id: int, contributes: bool) -> tuple[int | None, str | None]:
    """Record a personal play and optionally increment the durable archive count."""
    now = __import__("time").time()
    increment = 1 if contributes else 0
    with db() as conn:
        track = conn.execute("""
            UPDATE tracks
            SET play_count = play_count + ?,
                play_count_tag_dirty =
                    CASE WHEN ?=1 THEN 1 ELSE play_count_tag_dirty END
            WHERE id=?
            RETURNING play_count, path
        """, (increment, increment, track_id)).fetchone()
        if not track:
            return None, None
        conn.execute("""
            INSERT INTO user_play_counts (user_id, track_id, count, last_played_at)
            VALUES (?, ?, 1, ?)
            ON CONFLICT(user_id, track_id) DO UPDATE SET
                count = count + 1,
                last_played_at = excluded.last_played_at
        """, (user_id, track_id, now))
    return track["play_count"], track["path"]


def set_play_count(track_id: int, count: int):
    with db() as conn:
        conn.execute(
            "UPDATE tracks SET play_count = ? WHERE id = ?", (count, track_id)
        )


def merge_archive_play_count(track_id: int, count: int) -> bool:
    """Raise archive count to count, never lower it."""
    with db() as conn:
        cur = conn.execute("""
            UPDATE tracks
            SET play_count=?, play_count_tag_dirty=1
            WHERE id=? AND play_count < ?
        """, (count, track_id, count))
        return cur.rowcount > 0


def get_dirty_play_count_tags(limit: int = 500) -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT id, path, play_count
            FROM tracks
            WHERE play_count_tag_dirty=1
            ORDER BY id
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def mark_play_count_tag_written(track_id: int, written_count: int):
    with db() as conn:
        conn.execute("""
            UPDATE tracks SET play_count_tag_dirty=0
            WHERE id=? AND play_count <= ?
        """, (track_id, written_count))


def get_play_count_tag_status() -> dict:
    with db() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) FROM tracks WHERE play_count_tag_dirty=1"
        ).fetchone()[0]
    return {"pending": pending}


def get_setting(key: str, default=None):
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (key, value))


def log_audit(actor_id: int | None, action: str, target: str = "", details: str = ""):
    with db() as conn:
        conn.execute(
            "INSERT INTO audit_log (actor_id, action, target, details) VALUES (?,?,?,?)",
            (actor_id, action, target, details),
        )


def get_audit_log(limit: int = 100) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """SELECT a.id, a.action, a.target, a.details, a.created_at,
                      COALESCE(u.username, 'System') AS actor
               FROM audit_log a LEFT JOIN users u ON u.id=a.actor_id
               ORDER BY a.id DESC LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def del_setting(key: str):
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))


def claim_once(key: str) -> bool:
    """Atomically claim a one-off job key across multiple server workers."""
    with db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?,?)",
            (key, str(__import__("time").time())),
        )
        return cur.rowcount > 0


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
    if user_id:
        get_or_create_favorites(user_id)
    with db() as conn:
        rows = conn.execute(
            """SELECT p.id, p.owner_id, p.name, p.type, p.filters, p.sort,
                      p.is_system, p.system_key, p.created_at,
                      (SELECT COUNT(*) FROM playlist_tracks pt WHERE pt.playlist_id=p.id) AS track_count
               FROM playlists p
               WHERE (p.is_system=1 AND p.owner_id IS NULL) OR p.owner_id=?
               ORDER BY CASE WHEN p.system_key='favorites' THEN 0 ELSE 1 END,
                        p.is_system DESC, p.type ASC, p.created_at ASC""",
            (int(user_id),)
        ).fetchall()
    return [dict(r) for r in rows]


def create_playlist(user_id: int, name: str, filters: str, sort: str,
                    type_: str = "smart") -> int:
    if type_ not in ("smart", "static"):
        raise ValueError("invalid playlist type")
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO playlists (owner_id, name, type, filters, sort) VALUES (?,?,?,?,?)",
            (user_id, name, type_, filters, sort)
        )
        return cur.lastrowid


def next_playlist_name(user_id: int) -> str:
    """Return the next stable default name for a personal playlist."""
    import re

    with db() as conn:
        rows = conn.execute(
            """SELECT name FROM playlists
               WHERE owner_id=? AND is_system=0""",
            (int(user_id),),
        ).fetchall()
    highest = len(rows)
    for row in rows:
        match = re.fullmatch(r"Neue Playlist\s+(\d+)", (row["name"] or "").strip(), re.I)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"Neue Playlist {highest + 1}"


def get_personal_playlist(playlist_id: int, user_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute(
            """SELECT id, owner_id, name, type, filters, sort, is_system,
                      system_key, created_at
               FROM playlists
               WHERE id=? AND owner_id=? AND is_system=0""",
            (int(playlist_id), int(user_id)),
        ).fetchone()
    return dict(row) if row else None


def save_personal_playlist(user_id: int, name: str, type_: str, filters: str,
                           sort: str, track_ids: list[int],
                           playlist_id: int | None = None) -> int | None:
    """Create or replace a personal playlist and its ordered static tracks."""
    if type_ not in ("smart", "static"):
        raise ValueError("invalid playlist type")
    clean_ids = []
    seen = set()
    for value in track_ids:
        track_id = int(value)
        if track_id not in seen:
            clean_ids.append(track_id)
            seen.add(track_id)
    with db() as conn:
        if clean_ids:
            placeholders = ",".join("?" * len(clean_ids))
            existing = {
                int(row["id"]) for row in conn.execute(
                    f"SELECT id FROM tracks WHERE id IN ({placeholders})", clean_ids
                ).fetchall()
            }
            if len(existing) != len(clean_ids):
                raise ValueError("unknown track")
        if playlist_id is None:
            cur = conn.execute(
                """INSERT INTO playlists (owner_id, name, type, filters, sort)
                   VALUES (?,?,?,?,?)""",
                (int(user_id), name, type_, filters, sort),
            )
            playlist_id = int(cur.lastrowid)
        else:
            cur = conn.execute(
                """UPDATE playlists SET name=?, type=?, filters=?, sort=?
                   WHERE id=? AND owner_id=? AND is_system=0""",
                (name, type_, filters, sort, int(playlist_id), int(user_id)),
            )
            if cur.rowcount == 0:
                return None
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id=?", (int(playlist_id),))
        if type_ == "static":
            conn.executemany(
                """INSERT INTO playlist_tracks (playlist_id, track_id, added_at)
                   VALUES (?,?,?)""",
                [(int(playlist_id), track_id, index)
                 for index, track_id in enumerate(clean_ids, 1)],
            )
    return int(playlist_id)


def get_or_create_favorites(user_id: int) -> int:
    """Return the user's protected Favorites playlist, creating it if needed."""
    with db() as conn:
        row = conn.execute(
            "SELECT id FROM playlists WHERE owner_id=? AND system_key='favorites'",
            (int(user_id),)
        ).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            """INSERT INTO playlists
               (owner_id, name, type, filters, sort, is_system, system_key)
               VALUES (?, 'Favoriten', 'static', '{}', 'artist', 1, 'favorites')""",
            (int(user_id),)
        )
        return cur.lastrowid


def get_or_create_radio_favorites(user_id: int) -> int:
    """Backward-compatible alias for the unified Favorites playlist."""
    return get_or_create_favorites(user_id)


def set_favorite(user_id: int, track_id: int, favorite: bool) -> bool:
    playlist_id = get_or_create_favorites(user_id)
    with db() as conn:
        if not conn.execute("SELECT 1 FROM tracks WHERE id=?", (int(track_id),)).fetchone():
            return False
        if favorite:
            conn.execute("""
                INSERT OR IGNORE INTO playlist_tracks (playlist_id, track_id)
                VALUES (?, ?)
            """, (playlist_id, int(track_id)))
        else:
            conn.execute("""
                DELETE FROM playlist_tracks WHERE playlist_id=? AND track_id=?
            """, (playlist_id, int(track_id)))
    return True


def get_favorite_track_ids(user_id: int, track_ids: list[int] | None = None) -> set[int]:
    with db() as conn:
        playlist = conn.execute(
            "SELECT id FROM playlists WHERE owner_id=? AND system_key='favorites'",
            (int(user_id),),
        ).fetchone()
        if not playlist:
            return set()
        params: list[int] = [int(playlist["id"])]
        where = "WHERE playlist_id=?"
        if track_ids:
            clean_ids = [int(value) for value in track_ids]
            where += f" AND track_id IN ({','.join('?' * len(clean_ids))})"
            params.extend(clean_ids)
        rows = conn.execute(
            f"SELECT track_id FROM playlist_tracks {where}", params,
        ).fetchall()
    return {int(row["track_id"]) for row in rows}


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
                WHERE p.owner_id = ?
                  AND COALESCE(p.system_key, '') != 'favorites'
                  AND pt.track_id IN ({placeholders})""",
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
    """Resolve a visible playlist, dynamically for smart playlists."""
    with db() as conn:
        pl = conn.execute(
            "SELECT id, owner_id, type, filters, sort FROM playlists WHERE id=?", (playlist_id,)
        ).fetchone()
        if not pl or (pl["owner_id"] is not None and pl["owner_id"] != user_id):
            return None
        playlist = dict(pl)
    if playlist["type"] == "smart" and playlist["owner_id"] is not None:
        try:
            saved = json.loads(playlist.get("filters") or "{}")
        except (TypeError, json.JSONDecodeError):
            saved = {}
        if saved.get("editor_version") == 1:
            return get_playlist_filter_tracks(
                saved, user_id=user_id, sort=playlist.get("sort") or "artist",
                limit=5000,
            )
        # Compatibility with smart playlists created by the former sidebar UI.
        _, tracks = search_tracks(
            **{key: value for key, value in saved.items() if key in {
                "artist_query", "title_query", "album_query", "genre", "decade",
                "fmt", "min_dur", "max_dur", "min_bitrate", "year_min",
                "year_max", "bpm_min", "bpm_max", "loved_only",
            }},
            page=1, per_page=5000, sort=playlist.get("sort") or "artist",
            count=False, include_loved=True, user_id=user_id,
        )
        return tracks
    with db() as conn:
        rows = conn.execute(
            """SELECT t.id, t.path, t.title, t.artist, t.album, t.genre,
                      t.year, t.duration, t.bitrate, t.cover_hash, t.bpm,
                      CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved
               FROM playlist_tracks pt JOIN tracks t ON t.id = pt.track_id
               LEFT JOIN lastfm_loved_tracks l
                 ON l.user_id=?
                AND l.artist_norm=LOWER(COALESCE(t.artist, ''))
                AND l.title_norm=LOWER(COALESCE(t.title, ''))
               WHERE pt.playlist_id = ?
               ORDER BY pt.added_at""",
            (int(user_id), playlist_id,)
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
        d["loved"] = bool(d.get("loved"))
        tracks.append(d)
    return tracks


def _playlist_filter_tree(saved: dict) -> dict:
    search = saved.get("search") if isinstance(saved.get("search"), dict) else {}
    rules = saved.get("rules") if isinstance(saved.get("rules"), dict) else {
        "mode": "all", "rules": [],
    }
    combined = []
    for field in ("title", "artist", "album"):
        value = str(search.get(field) or "").strip()
        if value:
            combined.append({"field": field, "op": "contains", "value": value})
    clean_rules = validate_radio_filter(rules)
    if clean_rules["rules"]:
        combined.append(clean_rules)
    return validate_radio_filter({"mode": "all", "rules": combined})


def get_playlist_filter_tracks(saved: dict, user_id: int, sort: str = "artist",
                               limit: int = 500, random_order: bool = False,
                               exclude_ids: list[int] | None = None) -> list[dict]:
    """Return tracks matching a playlist-editor filter definition."""
    tree = _playlist_filter_tree(saved)
    where_sql, params = _radio_filter_sql(tree)
    conditions = [f"({where_sql})"] if where_sql else []
    excluded = [int(value) for value in (exclude_ids or [])]
    if excluded:
        conditions.append(f"t.id NOT IN ({','.join('?' * len(excluded))})")
        params.extend(excluded)
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    order_map = {
        "artist": "t.artist, t.album, t.track_no",
        "title": "t.title, t.artist",
        "album": "t.album, t.track_no",
        "year": "t.year DESC, t.artist",
        "duration": "t.duration DESC, t.artist",
        "top_played": "COALESCE(upc.count,0) DESC, t.artist",
    }
    order = "RANDOM()" if random_order else order_map.get(sort, order_map["artist"])
    limit = max(1, min(int(limit), 5000))
    uid = int(user_id or 0)
    with db() as conn:
        rows = conn.execute(
            f"""SELECT t.id, t.path, t.title, t.artist, t.album, t.genre,
                       t.year, t.track_no, t.duration, t.bitrate, t.size,
                       t.cover_hash, t.bpm,
                       COALESCE(upc.count,0) AS user_play_count,
                       upc.last_played_at,
                       CASE WHEN l.artist_norm IS NULL THEN 0 ELSE 1 END AS loved
                FROM tracks t
                LEFT JOIN user_play_counts upc
                       ON upc.track_id=t.id AND upc.user_id=?
                LEFT JOIN lastfm_loved_tracks l
                       ON l.user_id=?
                      AND l.artist_norm=LOWER(COALESCE(t.artist, ''))
                      AND l.title_norm=LOWER(COALESCE(t.title, ''))
                {where}
                ORDER BY {order}
                LIMIT ?""",
            [uid, uid] + params + [limit],
        ).fetchall()
    return _track_rows_to_dicts(rows)


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
