import os
import subprocess
import shlex
from datetime import datetime
from database import db

MOVIES_OUT = os.environ.get("MOVIES_OUT", "/vods/MisMovies")
SERIES_OUT = os.environ.get("SERIES_OUT", "/vods/MisSeries")


def _safe_name(name: str) -> str:
    """Remove characters unsafe for filesystem paths."""
    return name.replace("/", "-").replace("\\", "-").replace(":", " -").strip()


def _run_rsync(src: str, dst: str, delete: bool = False) -> tuple[bool, str]:
    """Run rsync safely. Returns (success, output)."""
    if not os.path.exists(src):
        return False, f"Source not found: {src}"
    os.makedirs(dst, exist_ok=True)
    cmd = ["rsync", "-av"]
    if delete:
        cmd.append("--delete")
    # Ensure trailing slash on src dir
    if os.path.isdir(src) and not src.endswith("/"):
        src = src + "/"
    cmd += [src, dst]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return result.returncode == 0, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "rsync timed out"
    except Exception as e:
        return False, str(e)


def _log_sync(media_id: int, action: str, details: str):
    with db() as conn:
        conn.execute(
            "INSERT INTO sync_history (media_id, action, details) VALUES (?,?,?)",
            (media_id, action, details)
        )


def sync_movie(media_id: int) -> dict:
    with db() as conn:
        row = conn.execute("""
            SELECT m.title, m.year, ms.source_path, ms.provider
            FROM media m
            JOIN media_sources ms ON ms.id = m.selected_source_id
            WHERE m.id=? AND m.media_type='movie'
        """, (media_id,)).fetchone()

        if not row:
            return {"ok": False, "msg": "Movie or source not found"}

        title = row["title"]
        year = row["year"]
        src = row["source_path"]

    folder_name = f"{_safe_name(title)} ({year})" if year else _safe_name(title)

    # Check if it belongs to a collection (boxset)
    with db() as conn:
        coll = conn.execute("""
            SELECT c.name FROM collections c
            JOIN collection_items ci ON ci.collection_id=c.id
            WHERE ci.media_id=? AND c.collection_type='movie'
        """, (media_id,)).fetchone()

    if coll:
        boxset_dir = os.path.join(MOVIES_OUT, f"{_safe_name(coll['name'])} [boxset]")
        dst = os.path.join(boxset_dir, folder_name)
    else:
        dst = os.path.join(MOVIES_OUT, folder_name)

    ok, output = _run_rsync(src, dst, delete=True)
    status = "synced" if ok else "available"

    with db() as conn:
        conn.execute("UPDATE media SET status=? WHERE id=?", (status, media_id))
        if ok:
            conn.execute("UPDATE media_sources SET synced=1 WHERE id=(SELECT selected_source_id FROM media WHERE id=?)", (media_id,))

    _log_sync(media_id, "sync_movie", f"{'OK' if ok else 'FAIL'}: {src} -> {dst}")
    return {"ok": ok, "msg": output[:500]}


def sync_series(media_id: int) -> dict:
    with db() as conn:
        row = conn.execute("""
            SELECT m.title, m.year, ms.source_path, ms.provider
            FROM media m
            JOIN media_sources ms ON ms.id = m.selected_source_id
            WHERE m.id=? AND m.media_type='series'
        """, (media_id,)).fetchone()

        if not row:
            return {"ok": False, "msg": "Series or source not found"}

        title = row["title"]
        src = row["source_path"]

    # Check if it belongs to a franchise
    with db() as conn:
        franchise = conn.execute("""
            SELECT c.name FROM collections c
            JOIN collection_items ci ON ci.collection_id=c.id
            WHERE ci.media_id=? AND c.collection_type='franchise'
        """, (media_id,)).fetchone()

    if franchise:
        franchise_dir = os.path.join(SERIES_OUT, _safe_name(franchise["name"]))
        dst = os.path.join(franchise_dir, _safe_name(title))
    else:
        dst = os.path.join(SERIES_OUT, _safe_name(title))

    ok, output = _run_rsync(src, dst, delete=True)
    status = "synced" if ok else "available"

    with db() as conn:
        conn.execute("UPDATE media SET status=? WHERE id=?", (status, media_id))
        if ok:
            conn.execute("UPDATE media_sources SET synced=1 WHERE id=(SELECT selected_source_id FROM media WHERE id=?)", (media_id,))

    _log_sync(media_id, "sync_series", f"{'OK' if ok else 'FAIL'}: {src} -> {dst}")
    return {"ok": ok, "msg": output[:500]}


def sync_collection(collection_id: int) -> dict:
    with db() as conn:
        items = conn.execute(
            "SELECT media_id FROM collection_items WHERE collection_id=?", (collection_id,)
        ).fetchall()

    results = []
    for item in items:
        mid = item["media_id"]
        with db() as conn:
            row = conn.execute("SELECT media_type FROM media WHERE id=?", (mid,)).fetchone()
        if row:
            if row["media_type"] == "movie":
                r = sync_movie(mid)
            else:
                r = sync_series(mid)
            results.append(r)

    ok_count = sum(1 for r in results if r["ok"])
    return {"ok": True, "synced": ok_count, "total": len(results)}


def remove_from_output(media_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT title, year, media_type FROM media WHERE id=?", (media_id,)).fetchone()
        if not row:
            return {"ok": False, "msg": "Not found"}

        title = row["title"]
        year = row["year"]
        mtype = row["media_type"]

    if mtype == "movie":
        folder_name = f"{_safe_name(title)} ({year})" if year else _safe_name(title)
        # Check boxset
        with db() as conn:
            coll = conn.execute("""
                SELECT c.name FROM collections c
                JOIN collection_items ci ON ci.collection_id=c.id
                WHERE ci.media_id=? AND c.collection_type='movie'
            """, (media_id,)).fetchone()
        if coll:
            path = os.path.join(MOVIES_OUT, f"{_safe_name(coll['name'])} [boxset]", folder_name)
        else:
            path = os.path.join(MOVIES_OUT, folder_name)
    else:
        path = os.path.join(SERIES_OUT, _safe_name(title))

    import shutil
    try:
        if os.path.exists(path):
            shutil.rmtree(path)
        with db() as conn:
            conn.execute("UPDATE media SET status='available' WHERE id=?", (media_id,))
            conn.execute("UPDATE media_sources SET synced=0 WHERE media_id=?", (media_id,))
        _log_sync(media_id, "remove", f"Removed: {path}")
        return {"ok": True, "msg": f"Removed {path}"}
    except Exception as e:
        return {"ok": False, "msg": str(e)}
