from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from database import db, db_read
import scanner
import sync as sync_engine
import media_collections as coll_engine
import asyncio

router = APIRouter(prefix="/api")


# ─── Models ──────────────────────────────────────────────────────────────────

class SelectSourceRequest(BaseModel):
    source_id: int

class AddCollectionRequest(BaseModel):
    collection_id: int
    mode: str  # "single" | "all"
    media_id: int


# ─── Media ───────────────────────────────────────────────────────────────────

@router.get("/media")
def list_media(
    media_type: Optional[str] = None,
    status: Optional[str] = None,
    provider: Optional[str] = None,
    q: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
):
    offset = (page - 1) * limit
    with db() as conn:
        if q:
            rows = conn.execute("""
                SELECT m.*, ms.provider as best_provider, ms.season_count, ms.episode_count,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id = m.selected_source_id
                WHERE m.title LIKE ?
                  AND (? IS NULL OR m.media_type=?)
                  AND (? IS NULL OR m.status=?)
                LIMIT ? OFFSET ?
            """, (f"%{q}%", media_type, media_type, status, status, limit, offset)).fetchall()
            total = len(rows)
        else:
            conditions = []
            params = []
            if media_type:
                conditions.append("m.media_type=?")
                params.append(media_type)
            if status:
                conditions.append("m.status=?")
                params.append(status)
            if provider:
                conditions.append("EXISTS(SELECT 1 FROM media_sources WHERE media_id=m.id AND provider=?)")
                params.append(provider)
            where = "WHERE " + " AND ".join(conditions) if conditions else ""

            total = conn.execute(
                f"SELECT COUNT(*) FROM media m {where}", params
            ).fetchone()[0]

            rows = conn.execute(f"""
                SELECT m.*, ms.provider as best_provider, ms.season_count, ms.episode_count,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id = m.selected_source_id
                {where}
                ORDER BY m.title
                LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

    return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}


@router.get("/media/{media_id}")
def get_media(media_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        sources = conn.execute(
            "SELECT * FROM media_sources WHERE media_id=? ORDER BY is_best DESC, season_count DESC",
            (media_id,)
        ).fetchall()
        people = conn.execute("""
            SELECT p.name, mp.role FROM people p
            JOIN media_people mp ON mp.person_id=p.id
            WHERE mp.media_id=?
        """, (media_id,)).fetchall()
        coll = None
        if row["collection_id"]:
            coll = conn.execute(
                "SELECT id, name, collection_type FROM collections WHERE id=?",
                (row["collection_id"],)
            ).fetchone()

    return {
        **dict(row),
        "sources": [dict(s) for s in sources],
        "people": [dict(p) for p in people],
        "collection": dict(coll) if coll else None,
    }


@router.post("/media/{media_id}/select-source")
def select_source(media_id: int, req: SelectSourceRequest):
    with db() as conn:
        src = conn.execute(
            "SELECT id FROM media_sources WHERE id=? AND media_id=?",
            (req.source_id, media_id)
        ).fetchone()
        if not src:
            raise HTTPException(404, "Source not found")
        conn.execute("UPDATE media SET selected_source_id=? WHERE id=?", (req.source_id, media_id))
    return {"ok": True}


@router.post("/media/{media_id}/sync")
def sync_media(media_id: int, background_tasks: BackgroundTasks):
    with db() as conn:
        row = conn.execute("SELECT media_type FROM media WHERE id=?", (media_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        mtype = row["media_type"]

    def do_sync():
        if mtype == "movie":
            sync_engine.sync_movie(media_id)
        else:
            sync_engine.sync_series(media_id)

    background_tasks.add_task(do_sync)
    return {"ok": True, "msg": "Sync started"}


@router.post("/media/{media_id}/remove")
def remove_media(media_id: int):
    result = sync_engine.remove_from_output(media_id)
    if not result["ok"]:
        raise HTTPException(400, result["msg"])
    return result


@router.post("/media/{media_id}/fetch-meta")
async def fetch_meta(media_id: int):
    await scanner.fetch_metadata_for_media(media_id)
    return {"ok": True}


# ─── Search ───────────────────────────────────────────────────────────────────

@router.get("/search")
def search(q: str = Query(..., min_length=1), media_type: Optional[str] = None):
    with db() as conn:
        rows = conn.execute("""
            SELECT m.id, m.title, m.year, m.media_type, m.status, m.poster_path,
                   ms.provider as best_provider, ms.season_count
            FROM media m
            LEFT JOIN media_sources ms ON ms.id = m.selected_source_id
            WHERE m.title LIKE ?
              AND (? IS NULL OR m.media_type=?)
            LIMIT 30
        """, (f"%{q}%", media_type, media_type)).fetchall()
    return [dict(r) for r in rows]


# ─── Providers ────────────────────────────────────────────────────────────────

@router.get("/providers")
def list_providers():
    with db() as conn:
        rows = conn.execute("""
            SELECT provider, COUNT(DISTINCT media_id) as count
            FROM media_sources GROUP BY provider ORDER BY count DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ─── Collections ─────────────────────────────────────────────────────────────

@router.get("/collections")
def list_collections(collection_type: Optional[str] = None):
    with db() as conn:
        q = """
            SELECT c.id, c.name, c.collection_type, COUNT(ci.media_id) as item_count
            FROM collections c
            LEFT JOIN collection_items ci ON ci.collection_id=c.id
        """
        params = []
        if collection_type:
            q += " WHERE c.collection_type=?"
            params.append(collection_type)
        q += " GROUP BY c.id ORDER BY c.name"
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/collections/{collection_id}")
def get_collection(collection_id: int):
    summary = coll_engine.get_collection_summary(collection_id)
    if not summary:
        raise HTTPException(404, "Collection not found")
    return summary


@router.post("/collections/{collection_id}/sync")
def sync_collection(collection_id: int, background_tasks: BackgroundTasks):
    background_tasks.add_task(sync_engine.sync_collection, collection_id)
    return {"ok": True, "msg": "Collection sync started"}


# ─── Scanner ─────────────────────────────────────────────────────────────────

@router.post("/scan")
def trigger_scan(background_tasks: BackgroundTasks):
    """Stage 1: fast scan in background. Returns immediately."""
    background_tasks.add_task(scanner.run_stage1)
    return {"ok": True, "msg": "Scan iniciado"}


@router.post("/scan/metadata")
async def fetch_metadata_batch(limit: int = 20):
    """Stage 2: fetch TMDB metadata for pending items."""
    count = await scanner.fetch_pending_metadata(limit)
    return {"fetched": count}


# ─── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats():
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        movies = conn.execute("SELECT COUNT(*) FROM media WHERE media_type='movie'").fetchone()[0]
        series = conn.execute("SELECT COUNT(*) FROM media WHERE media_type='series'").fetchone()[0]
        synced = conn.execute("SELECT COUNT(*) FROM media WHERE status='synced'").fetchone()[0]
        with_meta = conn.execute("SELECT COUNT(*) FROM media WHERE tmdb_id IS NOT NULL").fetchone()[0]
        providers = conn.execute("SELECT COUNT(DISTINCT provider) FROM media_sources").fetchone()[0]
        collections_count = conn.execute("SELECT COUNT(*) FROM collections").fetchone()[0]
    return {
        "total": total,
        "movies": movies,
        "series": series,
        "synced": synced,
        "with_meta": with_meta,
        "providers": providers,
        "collections": collections_count,
        "pending_meta": total - with_meta,
    }


# ─── Sync History ─────────────────────────────────────────────────────────────

@router.get("/sync-history")
def sync_history(limit: int = 50):
    with db() as conn:
        rows = conn.execute("""
            SELECT sh.*, m.title FROM sync_history sh
            LEFT JOIN media m ON m.id=sh.media_id
            ORDER BY sh.created_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]
