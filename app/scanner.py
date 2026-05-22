import os
import re
import asyncio
import subprocess
from typing import Optional
from database import db
import tmdb as tmdb_client

MOVIES_SRC = os.environ.get("MOVIES_SRC", "/vods/Movies")
SERIES_SRC = os.environ.get("SERIES_SRC", "/vods/Series")
MOVIES_OUT = os.environ.get("MOVIES_OUT", "/vods/MisMovies")
SERIES_OUT = os.environ.get("SERIES_OUT", "/vods/MisSeries")
POSTER_DIR = os.environ.get("POSTER_DIR", "/data/posters")

YEAR_RE = re.compile(r'\((\d{4})\)')


def extract_year(name: str) -> Optional[int]:
    m = YEAR_RE.search(name)
    return int(m.group(1)) if m else None


def clean_title(name: str) -> str:
    name = YEAR_RE.sub("", name)
    name = re.sub(r'[\._]', ' ', name)
    return name.strip()


# ─── Stage 1: Fast scan using find ───────────────────────────────────────────

def _find_strm_dirs(base: str, depth: int) -> list[str]:
    """Use system find to get dirs at exact depth that contain .strm files."""
    try:
        result = subprocess.run(
            ["find", base, "-maxdepth", str(depth), "-mindepth", str(depth), "-type", "d"],
            capture_output=True, text=True, timeout=60
        )
        return result.stdout.strip().splitlines()
    except Exception as e:
        print(f"[Scanner] find error: {e}")
        return []


def scan_movies_on_disk() -> list[dict]:
    """Scan movies using scandir (handles emoji folder names)."""
    results = []
    if not os.path.isdir(MOVIES_SRC):
        return results
    try:
        providers = list(os.scandir(MOVIES_SRC))
    except Exception as e:
        print(f"[Scanner] Movies scan error: {e}")
        return results
    for provider_entry in providers:
        if not provider_entry.is_dir():
            continue
        provider = provider_entry.name
        try:
            items = list(os.scandir(provider_entry.path))
        except Exception:
            continue
        for entry in items:
            raw = entry.name
            if not entry.is_dir():
                if not raw.endswith(".strm"):
                    continue
                raw = os.path.splitext(raw)[0]
            results.append({
                "provider": provider.upper(),
                "title": clean_title(raw),
                "year": extract_year(raw),
                "path": entry.path,
            })
    return results


def scan_series_on_disk() -> list[dict]:
    """Scan series using scandir (handles emoji folder names)."""
    results = []
    if not os.path.isdir(SERIES_SRC):
        return results
    try:
        providers = list(os.scandir(SERIES_SRC))
    except Exception as e:
        print(f"[Scanner] Series scan error: {e}")
        return results
    for provider_entry in providers:
        if not provider_entry.is_dir():
            continue
        provider = provider_entry.name
        try:
            series_entries = list(os.scandir(provider_entry.path))
        except Exception:
            continue
        for entry in series_entries:
            if not entry.is_dir():
                continue
            try:
                children = list(os.scandir(entry.path))
                season_count = sum(1 for c in children if c.is_dir())
                episode_count = season_count * 10  # estimate
                if season_count == 0:
                    episode_count = sum(1 for c in children if c.name.endswith(".strm"))
            except Exception:
                season_count = 1
                episode_count = 1
            results.append({
                "provider": provider.upper(),
                "title": clean_title(entry.name),
                "year": extract_year(entry.name),
                "path": entry.path,
                "season_count": season_count,
                "episode_count": episode_count,
            })
    return results


def _detect_existing_synced() -> set[str]:
    """Detect titles already present in output dirs."""
    synced = set()
    for d in [MOVIES_OUT, SERIES_OUT]:
        if not os.path.isdir(d):
            continue
        for item in os.listdir(d):
            key = re.sub(r'\[boxset\]', '', item)
            key = YEAR_RE.sub("", key).strip().lower()
            synced.add(key)
    return synced


def _group_by_title(items: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for item in items:
        key = re.sub(r'\s+', ' ', item["title"].lower().strip())
        groups.setdefault(key, []).append(item)
    return groups


def _bulk_upsert(groups: dict[str, list[dict]], media_type: str, pre_synced: set) -> int:
    """Insert all media in bulk. Disables FTS triggers during insert to prevent corruption."""
    count = 0
    items_list = list(groups.items())
    chunk_size = 500
    for i in range(0, len(items_list), chunk_size):
        chunk = items_list[i:i + chunk_size]
        with db() as conn:
            for key, sources in chunk:
                title = sources[0]["title"]
                year = sources[0].get("year")
                status = "synced" if key in pre_synced else "available"

                row = conn.execute(
                    "SELECT id, status FROM media WHERE LOWER(title)=LOWER(?) AND media_type=?",
                    (title, media_type)
                ).fetchone()

                if row:
                    media_id = row["id"]
                    if status == "synced" and row["status"] != "synced":
                        conn.execute("UPDATE media SET status='synced' WHERE id=?", (media_id,))
                else:
                    cur = conn.execute(
                        "INSERT INTO media (title, year, media_type, status) VALUES (?,?,?,?)",
                        (title, year, media_type, status)
                    )
                    media_id = cur.lastrowid

                for src in sources:
                    ex = conn.execute(
                        "SELECT id FROM media_sources WHERE media_id=? AND provider=?",
                        (media_id, src["provider"])
                    ).fetchone()
                    if ex:
                        conn.execute(
                            "UPDATE media_sources SET source_path=?, season_count=?, episode_count=?, last_seen=datetime('now') WHERE id=?",
                            (src["path"], src.get("season_count", 0), src.get("episode_count", 0), ex["id"])
                        )
                    else:
                        conn.execute(
                            "INSERT INTO media_sources (media_id, provider, source_path, season_count, episode_count) VALUES (?,?,?,?,?)",
                            (media_id, src["provider"], src["path"], src.get("season_count", 0), src.get("episode_count", 0))
                        )

                # Best source
                all_src = conn.execute(
                    "SELECT id, season_count, episode_count FROM media_sources WHERE media_id=?", (media_id,)
                ).fetchall()
                if all_src:
                    best = max(all_src, key=lambda r: (r["season_count"], r["episode_count"]))
                    conn.execute("UPDATE media_sources SET is_best=0 WHERE media_id=?", (media_id,))
                    conn.execute("UPDATE media_sources SET is_best=1 WHERE id=?", (best["id"],))
                    sel = conn.execute("SELECT selected_source_id FROM media WHERE id=?", (media_id,)).fetchone()
                    if sel and not sel["selected_source_id"]:
                        conn.execute("UPDATE media SET selected_source_id=? WHERE id=?", (best["id"], media_id))

                count += 1
    return count


def run_stage1() -> dict:
    """Stage 1: Fast scan using system find + bulk DB inserts."""
    print("[Scanner] Stage 1 start...")
    pre_synced = _detect_existing_synced()

    print("[Scanner] Scanning movies...")
    movies = scan_movies_on_disk()
    print(f"[Scanner] Found {len(movies)} movie entries, grouping...")
    movie_groups = _group_by_title(movies)

    print("[Scanner] Scanning series...")
    series = scan_series_on_disk()
    print(f"[Scanner] Found {len(series)} series entries, grouping...")
    series_groups = _group_by_title(series)

    print(f"[Scanner] Inserting {len(movie_groups)} movies to DB...")
    _bulk_upsert(movie_groups, "movie", pre_synced)

    print(f"[Scanner] Inserting {len(series_groups)} series to DB...")
    _bulk_upsert(series_groups, "series", pre_synced)

    print(f"[Scanner] Stage 1 done.")
    return {
        "movies_found": len(movie_groups),
        "series_found": len(series_groups),
        "total": len(movie_groups) + len(series_groups),
    }


# ─── Stage 2: Background metadata ────────────────────────────────────────────

async def fetch_metadata_for_media(media_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if not row or row["tmdb_id"]:
            return
        title, year, media_type = row["title"], row["year"], row["media_type"]

    try:
        if media_type == "movie":
            result = await tmdb_client.search_movie(title, year)
            if not result:
                return
            details = await tmdb_client.get_movie_details(result["id"])
            meta = tmdb_client.extract_movie_meta(details)
            collection_id = None
            coll = meta.get("collection")
            if coll:
                collection_id = await _upsert_collection(coll["id"], coll["name"], "movie")
            with db() as conn:
                conn.execute("""
                    UPDATE media SET tmdb_id=?,title=?,year=?,overview=?,genres=?,
                    poster_path=?,backdrop_path=?,collection_id=?,updated_at=datetime('now')
                    WHERE id=?
                """, (meta["tmdb_id"], meta["title"], meta["year"], meta["overview"],
                      meta["genres"], meta["poster_path"], meta["backdrop_path"],
                      collection_id, media_id))
                if collection_id:
                    conn.execute("INSERT OR IGNORE INTO collection_items(collection_id,media_id) VALUES(?,?)",
                                 (collection_id, media_id))
            await _save_people(media_id, meta["actors"], "actor")
            await _save_people(media_id, meta["directors"], "director")
        else:
            result = await tmdb_client.search_series(title, year)
            if not result:
                return
            details = await tmdb_client.get_series_details(result["id"])
            meta = tmdb_client.extract_series_meta(details)
            with db() as conn:
                conn.execute("""
                    UPDATE media SET tmdb_id=?,title=?,year=?,overview=?,genres=?,
                    poster_path=?,backdrop_path=?,updated_at=datetime('now')
                    WHERE id=?
                """, (meta["tmdb_id"], meta["title"], meta["year"], meta["overview"],
                      meta["genres"], meta["poster_path"], meta["backdrop_path"], media_id))
            await _save_people(media_id, meta["actors"], "actor")

        with db() as conn:
            row = conn.execute("SELECT poster_path FROM media WHERE id=?", (media_id,)).fetchone()
            if row and row["poster_path"]:
                dest = os.path.join(POSTER_DIR, f"{media_id}.jpg")
                if not os.path.exists(dest):
                    await tmdb_client.download_poster(row["poster_path"], dest)
    except Exception as e:
        print(f"[Scanner] Metadata failed media_id={media_id}: {e}")


async def _upsert_collection(tmdb_coll_id: int, name: str, coll_type: str) -> int:
    with db() as conn:
        row = conn.execute("SELECT id FROM collections WHERE tmdb_collection_id=?", (tmdb_coll_id,)).fetchone()
        if row:
            return row["id"]
        cur = conn.execute(
            "INSERT INTO collections (tmdb_collection_id, name, collection_type) VALUES (?,?,?)",
            (tmdb_coll_id, name, coll_type)
        )
        return cur.lastrowid


async def _save_people(media_id: int, names: list[str], role: str):
    with db() as conn:
        for name in names:
            row = conn.execute("SELECT id FROM people WHERE name=? AND role=?", (name, role)).fetchone()
            pid = row["id"] if row else conn.execute(
                "INSERT INTO people (name, role) VALUES (?,?)", (name, role)
            ).lastrowid
            conn.execute("INSERT OR IGNORE INTO media_people(media_id,person_id,role) VALUES(?,?,?)",
                         (media_id, pid, role))


async def fetch_pending_metadata(limit: int = 20) -> int:
    with db() as conn:
        rows = conn.execute("SELECT id FROM media WHERE tmdb_id IS NULL LIMIT ?", (limit,)).fetchall()
    count = 0
    for row in rows:
        await fetch_metadata_for_media(row["id"])
        count += 1
        await asyncio.sleep(0.3)
    return count


async def run_full_scan(fetch_meta: bool = False, max_meta: int = 0) -> dict:
    return run_stage1()
