import hashlib
import logging
import os
import threading
import time

from mutagen import File as MutagenFile

from db import save_cover, upsert_track

log = logging.getLogger(__name__)

_status = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_file": "",
    "errors": 0,
    "started_at": None,
    "finished_at": None,
}
_lock = threading.Lock()


def status():
    with _lock:
        return dict(_status)


def _update(**kw):
    with _lock:
        _status.update(kw)


def _tag_str(tags, *keys):
    for key in keys:
        val = tags.get(key)
        if val:
            return str(val[0]).strip() or None
    return None


def _tag_int(tags, *keys):
    raw = _tag_str(tags, *keys)
    if raw:
        try:
            return int(raw.split("/")[0])
        except ValueError:
            pass
    return None


def _extract_cover(audio):
    """Return (hash, bytes, mime) or (None, None, None)."""
    tags = audio.tags
    if tags is None:
        return None, None, None

    # ID3 APIC
    for key in tags:
        if key.startswith("APIC"):
            pic = tags[key]
            data = pic.data
            mime = pic.mime or "image/jpeg"
            h = hashlib.sha1(data, usedforsecurity=False).hexdigest()
            return h, data, mime

    # MP4 / FLAC / Ogg cover
    for attr in ("covr", "METADATA_BLOCK_PICTURE", "metadata_block_picture"):
        val = tags.get(attr)
        if val:
            pic = val[0]
            if hasattr(pic, "data"):
                data = pic.data
                mime = getattr(pic, "mime", "image/jpeg") or "image/jpeg"
            else:
                data = bytes(pic)
                mime = "image/jpeg"
            h = hashlib.sha1(data, usedforsecurity=False).hexdigest()
            return h, data, mime

    return None, None, None


def _scan_file(path: str) -> dict | None:
    try:
        stat = os.stat(path)
        audio = MutagenFile(path, easy=False)
        if audio is None:
            return None

        tags = audio.tags or {}

        # Try easy tags for common fields
        easy = MutagenFile(path, easy=True)
        etags = easy.tags if easy and easy.tags else {}

        def pick(*keys):
            for k in keys:
                v = etags.get(k) or tags.get(k)
                if v:
                    return str(v[0]).strip() or None
            return None

        def pick_int(*keys):
            raw = pick(*keys)
            if raw:
                try:
                    return int(str(raw).split("/")[0])
                except ValueError:
                    pass
            return None

        # Read BPM from tag (TBPM for MP3, FMPS_RATING/BPM for others)
        bpm = None
        for bpm_key in ("TBPM", "BPM", "bpm", "----:com.apple.iTunes:BPM"):
            raw = tags.get(bpm_key)
            if raw:
                try:
                    bpm = round(float(str(raw[0]).strip()), 2)
                    if bpm > 0:
                        break
                except (ValueError, TypeError):
                    pass

        cover_hash, cover_data, cover_mime = _extract_cover(audio)
        if cover_hash and cover_data:
            save_cover(cover_hash, cover_data, cover_mime)

        info = audio.info
        duration = int(getattr(info, "length", 0))
        bitrate = int(getattr(info, "bitrate", 0) / 1000) if hasattr(info, "bitrate") else 0

        # Read existing play count from tag
        play_count = 0
        try:
            pcnt = tags.get("PCNT")                          # MP3 ID3
            if pcnt is not None:
                play_count = int(pcnt.count)
            else:
                raw = (tags.get("play_count")                # FLAC Vorbis
                       or tags.get("----:com.apple.iTunes:play_count"))  # M4A
                if raw:
                    value = raw[0]
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="ignore")
                    play_count = int(str(value).strip())
        except Exception:
            pass

        # Read loved status from tag (TXXX:LOVE RATING for MP3, LOVE RATING vorbis comment for others)
        loved = False
        try:
            txxx = tags.get("TXXX:LOVE RATING")              # MP3
            if txxx is not None:
                loved = str(txxx).strip().upper() == "L"
            else:
                raw = (tags.get("LOVE RATING")               # FLAC/OGG
                       or tags.get("----:com.apple.iTunes:LOVE RATING"))  # M4A
                if raw:
                    loved = str(raw[0]).strip().upper() == "L"
        except Exception:
            pass

        return {
            "path": path,
            "title": pick("title", "TIT2"),
            "artist": pick("artist", "TPE1", "TPE2"),
            "album": pick("album", "TALB"),
            "genre": pick("genre", "TCON"),
            "year": pick_int("date", "TDRC", "TYER"),
            "track_no": pick_int("tracknumber", "TRCK"),
            "duration": duration,
            "bitrate": bitrate,
            "size": stat.st_size,
            "cover_hash": cover_hash,
            "bpm": bpm,
            "mtime": stat.st_mtime,
            "play_count": play_count,
            "loved": loved,
        }
    except Exception as e:
        log.warning("Failed to scan %s: %s", path, e)
        return None


def _collect_mp3s(root: str):
    extensions = {".mp3", ".flac", ".m4a", ".ogg", ".opus", ".aac", ".wav"}
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            if os.path.splitext(fname)[1].lower() in extensions:
                yield os.path.join(dirpath, fname)


def _read_bpm_tag(path: str) -> float | None:
    """Read BPM from file tag without full scan. Returns None if not found."""
    try:
        audio = MutagenFile(path, easy=False)
        if audio is None:
            return None
        tags = audio.tags or {}
        for key in ("TBPM", "BPM", "bpm", "----:com.apple.iTunes:BPM"):
            raw = tags.get(key)
            if raw:
                try:
                    val = round(float(str(raw[0]).strip()), 2)
                    if val > 0:
                        return val
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass
    return None


def _write_bpm_tag(path: str, bpm: float):
    """Write BPM value into the file's tag (TBPM for MP3, BPM for FLAC/OGG, BPM for M4A)."""
    ext = os.path.splitext(path)[1].lower()
    bpm_str = str(int(round(bpm)))

    if ext == ".mp3":
        from mutagen.id3 import ID3, TBPM
        try:
            tags = ID3(path)
        except Exception:
            tags = ID3()
        tags["TBPM"] = TBPM(encoding=3, text=bpm_str)
        tags.save(path)

    elif ext == ".flac":
        from mutagen.flac import FLAC
        audio = FLAC(path)
        audio["BPM"] = [bpm_str]
        audio.save()

    elif ext in (".ogg", ".opus"):
        from mutagen.oggvorbis import OggVorbis
        audio = OggVorbis(path)
        audio["BPM"] = [bpm_str]
        audio.save()

    elif ext in (".m4a", ".mp4", ".aac"):
        from mutagen.mp4 import MP4
        audio = MP4(path)
        audio["tmpo"] = [int(round(bpm))]
        audio.save()


def read_love_tag(path: str) -> bool | None:
    """Return True/False if LOVE RATING tag exists, None if absent."""
    try:
        ext = os.path.splitext(path)[1].lower()
        audio = MutagenFile(path, easy=False)
        if audio is None:
            return None
        tags = audio.tags or {}
        if ext == ".mp3":
            txxx = tags.get("TXXX:LOVE RATING")
            if txxx is None:
                return None
            return str(txxx).strip().upper() == "L"
        else:
            raw = tags.get("LOVE RATING") or tags.get("----:com.apple.iTunes:LOVE RATING")
            if not raw:
                return None
            return str(raw[0]).strip().upper() == "L"
    except Exception:
        return None


def write_love_tag(path: str, loved: bool):
    """Write LOVE RATING tag into the file (skips if already matches)."""
    current = read_love_tag(path)
    if current == loved:
        return  # already correct, skip
    ext = os.path.splitext(path)[1].lower()
    value = "L" if loved else ""

    if ext == ".mp3":
        from mutagen.id3 import ID3, TXXX
        try:
            tags = ID3(path)
        except Exception:
            tags = ID3()
        if loved:
            tags["TXXX:LOVE RATING"] = TXXX(encoding=3, desc="LOVE RATING", text=value)
        else:
            tags.delall("TXXX:LOVE RATING")
        tags.save(path)

    elif ext == ".flac":
        from mutagen.flac import FLAC
        audio = FLAC(path)
        if loved:
            audio["LOVE RATING"] = [value]
        else:
            audio.pop("LOVE RATING", None)
        audio.save()

    elif ext in (".ogg", ".opus"):
        from mutagen.oggvorbis import OggVorbis
        audio = OggVorbis(path)
        if loved:
            audio["LOVE RATING"] = [value]
        else:
            audio.pop("LOVE RATING", None)
        audio.save()

    elif ext in (".m4a", ".mp4", ".aac"):
        from mutagen.mp4 import MP4
        audio = MP4(path)
        key = "----:com.apple.iTunes:LOVE RATING"
        if loved:
            audio[key] = [value.encode()]
        else:
            audio.pop(key, None)
        audio.save()


def run_thumb_generation():
    """Generate missing cover thumbnails in the background after a scan."""
    def _worker():
        try:
            import io as _io
            import os as _os

            from PIL import Image

            from app import _THUMB_DIR, _THUMB_SIZE, _thumb_path
            from db import get_connection

            conn = get_connection()
            rows = conn.execute("SELECT hash, data, mime FROM covers").fetchall()
            conn.close()

            _os.makedirs(_THUMB_DIR, exist_ok=True)
            generated = 0
            for row in rows:
                tp = _thumb_path(row["hash"])
                if _os.path.exists(tp):
                    continue
                try:
                    img = Image.open(_io.BytesIO(row["data"]))
                    img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
                    with open(tp, "wb") as f:
                        img_buf = _io.BytesIO()
                        img.save(img_buf, format="WEBP", quality=75, method=4)
                        f.write(img_buf.getvalue())
                    generated += 1
                except Exception as e:
                    log.debug("Thumb failed for %s: %s", row["hash"], e)

            log.info("Thumbnail generation: %d generated", generated)
        except Exception as e:
            log.error("Thumbnail generation failed: %s", e)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def run_bpm_scan(limit: int = 0):
    """Analyse BPM for all tracks that don't have one yet.
    Runs in background after the regular scan.
    limit=0 means no limit (scan all).
    """
    def _bpm_worker():
        try:
            import librosa

            from db import get_connection
            conn = get_connection()
            try:
                query = "SELECT id, path FROM tracks WHERE bpm IS NULL OR bpm = 0"
                if limit:
                    query += f" LIMIT {int(limit)}"
                rows = conn.execute(query).fetchall()
            finally:
                conn.close()

            log.info("BPM scan: %d tracks to analyse", len(rows))
            for row in rows:
                try:
                    y, sr = librosa.load(row["path"], mono=True, duration=60)
                    tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
                    bpm = round(float(tempo), 2)

                    # Write TBPM tag back into the file
                    try:
                        _write_bpm_tag(row["path"], bpm)
                    except Exception as tag_err:
                        log.debug("Could not write TBPM tag to %s: %s", row["path"], tag_err)

                    # Save to DB
                    conn2 = get_connection()
                    try:
                        conn2.execute(
                            "UPDATE tracks SET bpm=? WHERE id=? AND (bpm IS NULL OR bpm=0)",
                            (bpm, row["id"])
                        )
                        conn2.commit()
                    finally:
                        conn2.close()
                except Exception as e:
                    log.debug("BPM failed for %s: %s", row["path"], e)
        except ImportError:
            log.warning("librosa not installed — BPM scan skipped")
        except Exception as e:
            log.error("BPM scan error: %s", e)

    t = threading.Thread(target=_bpm_worker, daemon=True)
    t.start()


def run_scan(music_root: str):
    if _status["running"]:
        return

    def _worker():
        _update(running=True, progress=0, total=0, errors=0, skipped=0,
                started_at=time.time(), finished_at=None, current_file="")
        try:
            # Load existing mtimes once — avoids per-file DB round-trips
            from db import get_connection
            conn = get_connection()
            try:
                existing_mtimes = {
                    row["path"]: row["mtime"]
                    for row in conn.execute("SELECT path, mtime FROM tracks").fetchall()
                }
            finally:
                conn.close()

            files = list(_collect_mp3s(music_root))
            _update(total=len(files))
            skipped = 0
            for i, path in enumerate(files):
                _update(current_file=path, progress=i + 1)
                try:
                    mtime = os.stat(path).st_mtime
                except OSError:
                    continue
                # Skip unchanged files
                if path in existing_mtimes and abs(existing_mtimes[path] - mtime) < 1.0:
                    skipped += 1
                    _update(skipped=skipped)
                    continue
                data = _scan_file(path)
                if data:
                    upsert_track(data)
                else:
                    with _lock:
                        _status["errors"] += 1
        except Exception as e:
            log.error("Scanner error: %s", e)
        finally:
            _update(running=False, finished_at=time.time(), current_file="")
            # Kick off background BPM analysis for new tracks
            run_bpm_scan()
            # Generate missing cover thumbnails in background
            run_thumb_generation()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
