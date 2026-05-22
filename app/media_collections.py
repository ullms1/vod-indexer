import asyncio
from database import db
import tmdb as tmdb_client

# Predefined franchise mappings for TV series
FRANCHISE_MAPPINGS: dict[str, list[str]] = {
    "Star Trek Universe": [
        "star trek", "the next generation", "deep space nine", "voyager",
        "enterprise", "discovery", "picard", "strange new worlds", "lower decks", "prodigy"
    ],
    "Doctor Who Universe": [
        "doctor who", "torchwood", "the sarah jane adventures", "class"
    ],
    "Dragon Ball Universe": [
        "dragon ball", "dragon ball z", "dragon ball gt", "dragon ball super",
        "dragon ball heroes"
    ],
    "MCU Series": [
        "wanda vision", "wandavision", "loki", "hawkeye", "moon knight",
        "ms marvel", "she-hulk", "secret invasion", "echo", "agatha",
        "what if", "daredevil born again", "iron heart"
    ],
    "Arrowverse": [
        "arrow", "the flash", "supergirl", "legends of tomorrow",
        "black lightning", "batwoman", "superman & lois", "naomi", "stargirl"
    ],
    "One Piece Universe": [
        "one piece"
    ],
    "Naruto Universe": [
        "naruto", "naruto shippuden", "boruto"
    ],
}


def _normalize(s: str) -> str:
    return s.lower().strip()


def detect_franchise(title: str) -> str | None:
    """Return franchise name if title matches any mapping."""
    t = _normalize(title)
    for franchise, keywords in FRANCHISE_MAPPINGS.items():
        for kw in keywords:
            if kw in t or t in kw:
                return franchise
    return None


async def assign_franchises():
    """Scan all series and assign franchise collections."""
    with db() as conn:
        series_list = conn.execute(
            "SELECT id, title FROM media WHERE media_type='series'"
        ).fetchall()

    for row in series_list:
        franchise = detect_franchise(row["title"])
        if not franchise:
            continue

        with db() as conn:
            coll = conn.execute(
                "SELECT id FROM collections WHERE name=? AND collection_type='franchise'",
                (franchise,)
            ).fetchone()
            if not coll:
                cur = conn.execute(
                    "INSERT INTO collections (name, collection_type) VALUES (?, 'franchise')",
                    (franchise,)
                )
                coll_id = cur.lastrowid
            else:
                coll_id = coll["id"]

            conn.execute(
                "INSERT OR IGNORE INTO collection_items(collection_id, media_id) VALUES(?,?)",
                (coll_id, row["id"])
            )
            conn.execute(
                "UPDATE media SET collection_id=? WHERE id=? AND collection_id IS NULL",
                (coll_id, row["id"])
            )


async def fetch_tmdb_collection(collection_id: int) -> dict | None:
    """Fetch full TMDB collection data and update DB."""
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM collections WHERE id=?", (collection_id,)
        ).fetchone()
        if not row or not row["tmdb_collection_id"]:
            return None
        tmdb_coll_id = row["tmdb_collection_id"]

    try:
        data = await tmdb_client.get_collection(tmdb_coll_id)
        parts = data.get("parts", [])
        with db() as conn:
            conn.execute(
                "UPDATE collections SET overview=?, poster_path=? WHERE id=?",
                (data.get("overview", ""), data.get("poster_path", ""), collection_id)
            )
        return {"name": data.get("name"), "parts": len(parts), "parts_data": parts}
    except Exception as e:
        print(f"[Collections] Failed to fetch TMDB collection {tmdb_coll_id}: {e}")
        return None


def get_collection_summary(collection_id: int) -> dict:
    with db() as conn:
        coll = conn.execute("SELECT * FROM collections WHERE id=?", (collection_id,)).fetchone()
        if not coll:
            return {}
        items = conn.execute("""
            SELECT m.id, m.title, m.year, m.status, m.poster_path
            FROM media m
            JOIN collection_items ci ON ci.media_id=m.id
            WHERE ci.collection_id=?
            ORDER BY m.year
        """, (collection_id,)).fetchall()
        return {
            "id": coll["id"],
            "name": coll["name"],
            "type": coll["collection_type"],
            "items": [dict(i) for i in items],
            "total": len(items),
        }


def get_all_collections() -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT c.id, c.name, c.collection_type, COUNT(ci.media_id) as item_count
            FROM collections c
            LEFT JOIN collection_items ci ON ci.collection_id=c.id
            GROUP BY c.id
            ORDER BY c.name
        """).fetchall()
        return [dict(r) for r in rows]
