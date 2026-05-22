import os
import httpx
import asyncio
from typing import Optional

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p/w200"
API_KEY = os.environ.get("TMDB_API_KEY", "")


async def _get(path: str, params: dict = {}) -> dict:
    params["api_key"] = API_KEY
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{TMDB_BASE}{path}", params=params)
        r.raise_for_status()
        return r.json()


async def search_movie(title: str, year: Optional[int] = None) -> Optional[dict]:
    params = {"query": title, "language": "es-MX"}
    if year:
        params["year"] = year
    data = await _get("/search/movie", params)
    results = data.get("results", [])
    return results[0] if results else None


async def search_series(title: str, year: Optional[int] = None) -> Optional[dict]:
    params = {"query": title, "language": "es-MX"}
    if year:
        params["first_air_date_year"] = year
    data = await _get("/search/tv", params)
    results = data.get("results", [])
    return results[0] if results else None


async def get_movie_details(tmdb_id: int) -> dict:
    return await _get(f"/movie/{tmdb_id}", {"language": "es-MX", "append_to_response": "credits,belongs_to_collection"})


async def get_series_details(tmdb_id: int) -> dict:
    return await _get(f"/tv/{tmdb_id}", {"language": "es-MX", "append_to_response": "credits,seasons"})


async def get_collection(collection_id: int) -> dict:
    return await _get(f"/collection/{collection_id}", {"language": "es-MX"})


def extract_movie_meta(details: dict) -> dict:
    genres = ",".join(g["name"] for g in details.get("genres", []))
    cast = details.get("credits", {}).get("cast", [])[:5]
    crew = details.get("credits", {}).get("crew", [])
    directors = [p["name"] for p in crew if p.get("job") == "Director"]
    actors = [p["name"] for p in cast]
    collection = details.get("belongs_to_collection")
    year = None
    rd = details.get("release_date", "")
    if rd:
        try:
            year = int(rd[:4])
        except ValueError:
            pass
    return {
        "tmdb_id": details["id"],
        "title": details.get("title", ""),
        "year": year,
        "overview": details.get("overview", ""),
        "genres": genres,
        "poster_path": details.get("poster_path", ""),
        "backdrop_path": details.get("backdrop_path", ""),
        "actors": actors,
        "directors": directors,
        "collection": collection,
    }


def extract_series_meta(details: dict) -> dict:
    genres = ",".join(g["name"] for g in details.get("genres", []))
    cast = details.get("credits", {}).get("cast", [])[:5]
    actors = [p["name"] for p in cast]
    seasons = [s for s in details.get("seasons", []) if s.get("season_number", 0) > 0]
    season_count = len(seasons)
    episode_count = sum(s.get("episode_count", 0) for s in seasons)
    year = None
    fd = details.get("first_air_date", "")
    if fd:
        try:
            year = int(fd[:4])
        except ValueError:
            pass
    return {
        "tmdb_id": details["id"],
        "title": details.get("name", ""),
        "year": year,
        "overview": details.get("overview", ""),
        "genres": genres,
        "poster_path": details.get("poster_path", ""),
        "backdrop_path": details.get("backdrop_path", ""),
        "actors": actors,
        "directors": [],
        "season_count": season_count,
        "episode_count": episode_count,
    }


async def download_poster(poster_path: str, dest_path: str) -> bool:
    if not poster_path:
        return False
    url = f"{TMDB_IMG}{poster_path}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url)
            r.raise_for_status()
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(r.content)
        return True
    except Exception as e:
        print(f"[TMDB] Poster download failed: {e}")
        return False
