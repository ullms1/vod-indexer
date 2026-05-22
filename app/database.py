import sqlite3
import os
import threading
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/media.db")

# Global write lock — serializes ALL writes to prevent corruption
_write_lock = threading.Lock()


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-4000")
    return conn


@contextmanager
def db():
    """Thread-safe DB context. Serializes all writes via lock."""
    with _write_lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@contextmanager
def db_read():
    """Read-only context — no lock needed."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER,
            media_type TEXT NOT NULL CHECK(media_type IN ('movie','series')),
            title TEXT NOT NULL,
            year INTEGER,
            overview TEXT,
            genres TEXT,
            poster_path TEXT,
            backdrop_path TEXT,
            status TEXT DEFAULT 'available',
            selected_source_id INTEGER,
            collection_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS media_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            source_path TEXT NOT NULL,
            season_count INTEGER DEFAULT 0,
            episode_count INTEGER DEFAULT 0,
            is_best INTEGER DEFAULT 0,
            synced INTEGER DEFAULT 0,
            last_seen TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_collection_id INTEGER,
            name TEXT NOT NULL,
            collection_type TEXT DEFAULT 'movie' CHECK(collection_type IN ('movie','franchise')),
            overview TEXT,
            poster_path TEXT
        );

        CREATE TABLE IF NOT EXISTS collection_items (
            collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
            media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
            sort_order INTEGER DEFAULT 0,
            PRIMARY KEY(collection_id, media_id)
        );

        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_person_id INTEGER UNIQUE,
            name TEXT NOT NULL,
            role TEXT
        );

        CREATE TABLE IF NOT EXISTS media_people (
            media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
            person_id INTEGER REFERENCES people(id) ON DELETE CASCADE,
            role TEXT,
            character_name TEXT,
            PRIMARY KEY(media_id, person_id, role)
        );

        CREATE TABLE IF NOT EXISTS sync_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            media_id INTEGER REFERENCES media(id) ON DELETE SET NULL,
            action TEXT NOT NULL,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_media_type ON media(media_type);
        CREATE INDEX IF NOT EXISTS idx_media_title ON media(title COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_media_status ON media(status);
        CREATE INDEX IF NOT EXISTS idx_media_tmdb ON media(tmdb_id);
        CREATE INDEX IF NOT EXISTS idx_sources_media ON media_sources(media_id);
        CREATE INDEX IF NOT EXISTS idx_sources_provider ON media_sources(provider);
        """)
    print(f"[DB] Initialized at {DB_PATH}")
