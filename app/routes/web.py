from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from typing import Optional
from database import db
import media_collections as coll_engine

router = APIRouter()
templates = Jinja2Templates(directory="/app/templates")


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
        synced = conn.execute("SELECT COUNT(*) FROM media WHERE status='synced'").fetchone()[0]
        movies = conn.execute("SELECT COUNT(*) FROM media WHERE media_type='movie'").fetchone()[0]
        series = conn.execute("SELECT COUNT(*) FROM media WHERE media_type='series'").fetchone()[0]
        pending = conn.execute("SELECT COUNT(*) FROM media WHERE tmdb_id IS NULL").fetchone()[0]
        recent = conn.execute("""
            SELECT m.id, m.title, m.year, m.media_type, m.status, m.poster_path,
                   ms.provider as best_provider
            FROM media m
            LEFT JOIN media_sources ms ON ms.id=m.selected_source_id
            ORDER BY m.created_at DESC LIMIT 12
        """).fetchall()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": {"total": total, "synced": synced, "movies": movies, "series": series, "pending": pending},
        "recent": [dict(r) for r in recent],
    })


@router.get("/movies", response_class=HTMLResponse)
def movies_page(
    request: Request,
    q: Optional[str] = None,
    provider: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
):
    limit = 48
    offset = (page - 1) * limit
    with db() as conn:
        conditions = ["m.media_type='movie'"]
        params: list = []
        if provider:
            conditions.append("EXISTS(SELECT 1 FROM media_sources WHERE media_id=m.id AND provider=?)")
            params.append(provider)
        if status:
            conditions.append("m.status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions)

        if q:
            items = conn.execute(f"""
                SELECT m.id, m.title, m.year, m.status, m.poster_path, m.genres,
                       ms.provider as best_provider,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id=m.selected_source_id
                WHERE m.title LIKE ? AND m.media_type='movie'
                LIMIT ? OFFSET ?
            """, (f"%{q}%", limit, offset)).fetchall()
            total = len(items)
        else:
            total = conn.execute(f"SELECT COUNT(*) FROM media m {where}", params).fetchone()[0]
            items = conn.execute(f"""
                SELECT m.id, m.title, m.year, m.status, m.poster_path, m.genres,
                       ms.provider as best_provider,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id=m.selected_source_id
                {where}
                ORDER BY m.title LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

        providers = conn.execute("""
            SELECT DISTINCT ms.provider FROM media_sources ms
            JOIN media m ON m.id=ms.media_id WHERE m.media_type='movie' ORDER BY ms.provider
        """).fetchall()

    return templates.TemplateResponse("movies.html", {
        "request": request,
        "items": [dict(i) for i in items],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "q": q or "",
        "provider": provider or "",
        "status": status or "",
        "providers": [r["provider"] for r in providers],
    })


@router.get("/series", response_class=HTMLResponse)
def series_page(
    request: Request,
    q: Optional[str] = None,
    provider: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
):
    limit = 48
    offset = (page - 1) * limit
    with db() as conn:
        conditions = ["m.media_type='series'"]
        params: list = []
        if provider:
            conditions.append("EXISTS(SELECT 1 FROM media_sources WHERE media_id=m.id AND provider=?)")
            params.append(provider)
        if status:
            conditions.append("m.status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(conditions)

        if q:
            items = conn.execute(f"""
                SELECT m.id, m.title, m.year, m.status, m.poster_path, m.genres,
                       ms.provider as best_provider, ms.season_count,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id=m.selected_source_id
                WHERE m.title LIKE ? AND m.media_type='series'
                LIMIT ? OFFSET ?
            """, (f"%{q}%", limit, offset)).fetchall()
            total = len(items)
        else:
            total = conn.execute(f"SELECT COUNT(*) FROM media m {where}", params).fetchone()[0]
            items = conn.execute(f"""
                SELECT m.id, m.title, m.year, m.status, m.poster_path, m.genres,
                       ms.provider as best_provider, ms.season_count,
                       (SELECT COUNT(*) FROM media_sources WHERE media_id=m.id) as source_count
                FROM media m
                LEFT JOIN media_sources ms ON ms.id=m.selected_source_id
                {where}
                ORDER BY m.title LIMIT ? OFFSET ?
            """, params + [limit, offset]).fetchall()

        providers = conn.execute("""
            SELECT DISTINCT ms.provider FROM media_sources ms
            JOIN media m ON m.id=ms.media_id WHERE m.media_type='series' ORDER BY ms.provider
        """).fetchall()

    return templates.TemplateResponse("series.html", {
        "request": request,
        "items": [dict(i) for i in items],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "q": q or "",
        "provider": provider or "",
        "status": status or "",
        "providers": [r["provider"] for r in providers],
    })


@router.get("/collections", response_class=HTMLResponse)
def collections_page(request: Request):
    all_collections = coll_engine.get_all_collections()
    movie_colls = [c for c in all_collections if c["collection_type"] == "movie"]
    franchises = [c for c in all_collections if c["collection_type"] == "franchise"]
    return templates.TemplateResponse("collections.html", {
        "request": request,
        "movie_collections": movie_colls,
        "franchises": franchises,
    })


@router.get("/media/{media_id}", response_class=HTMLResponse)
def media_detail(request: Request, media_id: int):
    with db() as conn:
        row = conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone()
        if not row:
            return HTMLResponse("Not found", status_code=404)
        sources = conn.execute(
            "SELECT * FROM media_sources WHERE media_id=? ORDER BY is_best DESC, season_count DESC",
            (media_id,)
        ).fetchall()
        people = conn.execute("""
            SELECT p.name, mp.role FROM people p
            JOIN media_people mp ON mp.person_id=p.id WHERE mp.media_id=?
        """, (media_id,)).fetchall()
        coll = None
        if row["collection_id"]:
            coll = conn.execute(
                "SELECT * FROM collections WHERE id=?", (row["collection_id"],)
            ).fetchone()

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "media": dict(row),
        "sources": [dict(s) for s in sources],
        "people": [dict(p) for p in people],
        "collection": dict(coll) if coll else None,
    })
