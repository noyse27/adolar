import sqlite3
import os
import json
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
                contributes_playcount INTEGER NOT NULL DEFAULT 0,
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
        ]:
            try:
                conn.execute(migration)
            except Exception:
                pass
        _seed_radio_stations(conn)
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
                   rs.created_at, rs.updated_at
            FROM radio_stations rs
            LEFT JOIN users u ON u.id=rs.owner_id
            WHERE """ + " OR ".join(where) + """
            GROUP BY rs.id
            ORDER BY rs.is_system DESC,
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
                   rs.created_at, rs.updated_at
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


def get_radio_station_tracks(station_id: int, count=25, exclude_ids=None, user_id=None) -> list[dict] | None:
    station = get_radio_station(station_id)
    if not station:
        return None
    return get_radio_filter_tracks(station.get("filter") or {}, count, exclude_ids, user_id=user_id)


def get_radio_filter_tracks(filter_def: dict, count=25, exclude_ids=None, user_id=None) -> list[dict]:
    count = max(1, min(int(count), 100))
    excl = [int(x) for x in (exclude_ids or []) if str(x).isdigit()]
    where_sql, params = _radio_filter_sql(filter_def or {})
    conditions = []
    if where_sql:
        conditions.append(f"({where_sql})")
    if excl:
        conditions.append("t.id NOT IN (" + ",".join("?" * len(excl)) + ")")
        params.extend(excl)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    uid = int(user_id or 0)
    with db() as conn:
        rows = conn.execute(f"""
            SELECT t.id, t.path, t.title, t.artist, t.album, t.genre, t.year, t.track_no,
                   t.duration, t.bitrate, t.size, t.cover_hash, t.bpm,
                   COALESCE(upc.count, 0) AS user_play_count, upc.last_played_at
            FROM tracks t
            LEFT JOIN user_play_counts upc ON upc.track_id=t.id AND upc.user_id=?
            {where}
            ORDER BY RANDOM()
            LIMIT ?
        """, [uid] + params + [count]).fetchall()
    return _track_rows_to_dicts(rows)


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
