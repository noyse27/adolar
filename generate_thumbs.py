#!/usr/bin/env python3
"""
Standalone thumbnail generator for Adolar covers.
Run this as a background process on the server to pre-generate all cover
thumbnails before starting Adolar, or to fill gaps without a full rescan.

Usage:
    python generate_thumbs.py
    python generate_thumbs.py --workers 4   # parallel generation
"""

import argparse
import io
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("generate_thumbs")

# Ensure app modules are importable
sys.path.insert(0, os.path.dirname(__file__))


def main():
    parser = argparse.ArgumentParser(description="Pre-generate Adolar cover thumbnails")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel worker threads (default: 4)")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate even if thumbnail already exists")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show failed cover hashes")
    args = parser.parse_args()

    from app import _THUMB_DIR, _THUMB_SIZE, _thumb_path
    from db import get_connection

    os.makedirs(_THUMB_DIR, exist_ok=True)

    conn = get_connection()
    rows = conn.execute("SELECT hash, data, mime FROM covers").fetchall()
    conn.close()

    total = len(rows)
    log.info("Found %d covers in database", total)

    skip = 0
    todo = []
    for row in rows:
        tp = _thumb_path(row["hash"])
        if os.path.exists(tp) and not args.force:
            skip += 1
        else:
            todo.append(row)

    log.info("Skipping %d existing thumbnails, generating %d", skip, len(todo))
    if not todo:
        log.info("All thumbnails up to date.")
        return

    from PIL import Image

    done = 0
    errors = 0
    failed = []

    def _generate(row):
        try:
            img = Image.open(io.BytesIO(row["data"]))
            img.thumbnail(_THUMB_SIZE, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="WEBP", quality=75, method=4)
            tp = _thumb_path(row["hash"])
            with open(tp, "wb") as f:
                f.write(buf.getvalue())
            return (True, None)
        except Exception as e:
            return (False, str(e))

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_generate, row): row["hash"] for row in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            ok, err = fut.result()
            hash_ = futures[fut]
            if ok:
                done += 1
            else:
                errors += 1
                failed.append((hash_, err))
            if i % 100 == 0 or i == len(todo):
                log.info("Progress: %d / %d (errors: %d)", i, len(todo), errors)

    log.info("Done. Generated: %d, Errors: %d", done, errors)

    if failed and args.verbose:
        log.info("\n--- Failed covers (%d) ---", len(failed))
        for hash_, err in failed:
            log.info("  %s: %s", hash_[:16], err)
    elif failed:
        log.info("Run with --verbose to see which covers failed (likely corrupt embedded images).")


if __name__ == "__main__":
    main()
