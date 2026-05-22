import os
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from database import init_db
from routes.api import router as api_router
from routes.web import router as web_router

POSTER_DIR = os.environ.get("POSTER_DIR", "/data/posters")
DATA_DIR = os.environ.get("DATA_DIR", "/data")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(POSTER_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="VOD-Indexer",
    version="1.0.0",
    docs_url="/api/docs",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="/app/static"), name="static")

app.include_router(api_router)
app.include_router(web_router)


@app.get("/poster/{media_id}")
def serve_poster(media_id: int):
    """Serve cached poster or fallback."""
    path = os.path.join(POSTER_DIR, f"{media_id}.jpg")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/jpeg")
    return FileResponse("/app/static/img/no-poster.svg", media_type="image/svg+xml")


@app.get("/health")
def health():
    return {"status": "ok"}
