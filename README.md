# VOD-Indexer

> A lightweight, self-hosted STRM library curation and synchronization layer for Jellyfin, Plex, and Emby.

![Python](https://img.shields.io/badge/Python-3.11-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green)
![Docker](https://img.shields.io/badge/Docker-required-blue)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## What is VOD-Indexer?

VOD-Indexer is **not** a media server. It is an intelligent indexing and curation layer that sits between your STRM provider (such as Dispatcharr) and your media server (Jellyfin, Plex, Emby).

**The problem it solves:**

IPTV/STRM providers generate massive libraries with thousands of files organized by provider folders. You do not want your media server scanning everything — most of it is duplicate, low quality, or simply not what you want.

**The solution:**

```
STRM Provider (Dispatcharr, etc.)
    down  READ ONLY
VOD-Indexer  <--  You curate here
    down  rsync (only what you selected)
Output Folders (MyMovies / MySeries)
    down
Jellyfin / Plex / Emby
```

---

## Features

- **Multi-source intelligence** — same title across multiple providers is grouped, best source recommended automatically
- **TMDB metadata** — posters, overviews, cast, genres, collections
- **Movie collections** — generates [boxset] folders compatible with Jellyfin
- **TV franchises** — groups related series (Star Trek, Dragon Ball, MCU, etc.)
- **Curated sync** — rsync only selected content to output folders
- **Fast search** — find anything across 30,000+ titles instantly
- **Provider filtering** — filter by provider, status, type
- **Two-stage scanning** — Stage 1 fast disk scan + Stage 2 background TMDB metadata
- **Telegram Bot** — remote control with approval mode
- **Low RAM** — ~80-150MB average

---

## Requirements

### System
- Linux (Ubuntu/Debian recommended)
- Docker 20.x or newer
- At least 1GB free disk space for database and posters

### Accounts
- TMDB API Key (free) — https://www.themoviedb.org/settings/api
- Telegram Bot Token (optional) — from @BotFather

### Source Directory Structure

VOD-Indexer expects your STRM source folders organized like this:

```
Movies/
├── PROVIDER_NAME/
│   ├── Movie Title (2023)/
│   │   └── movie.strm
│   └── Another Movie (2019)/
│       └── movie.strm
└── ANOTHER_PROVIDER/
    └── ...

Series/
├── PROVIDER_NAME/
│   ├── Series Title/
│   │   ├── Season 01/
│   │   │   ├── episode1.strm
│   │   │   └── episode2.strm
│   │   └── Season 02/
│   └── Another Series/
└── ANOTHER_PROVIDER/
    └── ...
```

This is the default output structure of Dispatcharr and most IPTV middleware solutions.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/vod-indexer.git
cd vod-indexer
```

### 2. Create output directories

These are the folders your media server will scan:

```bash
mkdir -p /your/path/to/MyMovies
mkdir -p /your/path/to/MySeries
```

### 3. Configure environment

```bash
cp .env.example .env
nano .env
```

Add your TMDB API key:
```
TMDB_API_KEY=your_key_here
```

**How to get a TMDB API Key:**
1. Create a free account at https://www.themoviedb.org/
2. Go to Settings -> API -> Create -> Developer
3. Copy the API Key (the short one, NOT the "API Read Access Token")

### 4. Edit docker-compose.yml

Replace the volume paths with your actual directories:

```yaml
volumes:
  - /home/user/dispatcharr/Movies:/vods/Movies:ro
  - /home/user/dispatcharr/Series:/vods/Series:ro
  - /home/user/media/MyMovies:/vods/MisMovies
  - /home/user/media/MySeries:/vods/MisSeries
  - ./data:/data
```

Source directories MUST be mounted as :ro (read-only). VOD-Indexer will never modify them.

### 5. Build and run

```bash
docker build -t vod-indexer .
docker compose up -d
```

### 6. Open the UI

```
http://localhost:3030
```

---

## Media Server Setup

### Jellyfin
1. Add a Movies library pointing to your MyMovies output folder
2. Add a TV Shows library pointing to your MySeries output folder
3. Enable "Merge movie box sets" in library settings for collection support
4. Jellyfin automatically detects [boxset] folders as collections

### Plex
1. Add a Movies library pointing to your MyMovies folder
2. Add a TV Shows library pointing to your MySeries folder

### Emby
Same as Jellyfin — add libraries pointing to your output folders.

Only add the output folders to your media server, not the source STRM folders.

---

## Usage Guide

### Step 1 — Scan your library

Click the Scan button in the top right. This runs a fast disk scan (Stage 1).

Watch the logs for confirmation:
```bash
docker logs vod-indexer -f
# Wait for: [Scanner] Stage 1 done.
```

### Step 2 — Fetch metadata (Stage 2)

After Stage 1 completes, click "Get metadata" on the dashboard, or run this loop for bulk fetching:

```bash
for i in $(seq 1 500); do
  curl -s -X POST "http://localhost:3030/api/scan/metadata?limit=20" > /dev/null
  echo "Batch $i done"
  sleep 5
done
```

This fetches 10,000 items with a 5-second pause between batches, safely within TMDB rate limits.

### Step 3 — Browse and curate

- Go to Movies or Series
- Search and filter to find what you want
- Click any title to open its detail page

### Step 4 — Sync to your media server

On any title's detail page click Sync to Jellyfin to copy it to your output folder.
Your media server will detect it on its next library scan.

---

## Multi-Source Intelligence

When the same title exists across multiple providers:

```
Dark (2017)
  STAR  VODLAT    -> 3 seasons  (best source, selected automatically)
  WARN  NETFLIX   -> 2 seasons
  WARN  CLOUDHO   -> 1 season
```

You can override the selected source from the detail page.

---

## Collections and Franchises

### Movie Collections
Synced as [boxset] folders:
```
MyMovies/
└── Harry Potter Collection [boxset]/
    ├── Harry Potter and the Sorcerer's Stone (2001)/
    └── ...
```

### TV Franchises
Synced as grouped folders:
```
MySeries/
└── Star Trek Universe/
    ├── The Next Generation/
    ├── Deep Space Nine/
    └── Picard/
```

Pre-configured franchises: Star Trek, Doctor Who, Dragon Ball, MCU Series, Arrowverse, One Piece, Naruto, and more.
You can add custom mappings in app/media_collections.py.

---

## API Reference

Full interactive docs: http://localhost:3030/api/docs

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/scan | Stage 1: fast disk scan |
| POST | /api/scan/metadata | Stage 2: fetch TMDB metadata |
| GET | /api/media | List media with filters |
| GET | /api/media/{id} | Get media detail |
| POST | /api/media/{id}/sync | Sync to output folder |
| POST | /api/media/{id}/remove | Remove from output folder |
| POST | /api/media/{id}/select-source | Change active source |
| GET | /api/search?q= | Search by title |
| GET | /api/stats | Global statistics |
| GET | /api/collections | List collections |
| POST | /api/collections/{id}/sync | Sync entire collection |
| GET | /api/providers | List detected providers |

---

## Telegram Bot (Optional)

```bash
cd telegram-bot
docker build -t vod-telegram-bot .
docker run -d \
  --name vod-telegram-bot \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN=your_token \
  -e VOD_INDEXER_API=http://your-server-ip:3030/api \
  -e ALLOWED_CHAT_IDS=your_chat_id \
  vod-telegram-bot
```

### Commands

| Command | Description |
|---------|-------------|
| /search title | Search for content |
| /recent | Recently indexed items |
| /selected | Synced to media server |
| /stats | Library statistics |
| /random | Random item |
| /sync id | Sync item (requires confirmation) |

The bot never syncs content without explicit user confirmation (Approval Mode).

---

## Project Structure

```
vod-indexer/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── database.py          # SQLite schema
│   ├── scanner.py           # Stage 1 and 2 scanner
│   ├── sync.py              # rsync engine
│   ├── tmdb.py              # TMDB API client
│   ├── media_collections.py # Collections and franchise detection
│   ├── routes/
│   │   ├── api.py           # REST API
│   │   └── web.py           # Web UI routes
│   ├── templates/           # HTML templates
│   └── static/              # CSS, JS, images
├── telegram-bot/
├── data/                    # Created at runtime
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Troubleshooting

**Scan finds 0 items:**
Verify volume paths in docker-compose.yml and source folder structure: Provider/Title/file.strm

**Metadata not fetching:**
- Use the short TMDB API Key (32 chars), not the long Bearer token
- Wait for Stage 1 done in logs before triggering Stage 2

**Sync fails:**
Ensure output directories exist and are writable by Docker

**Database issues:**
Stop the container, delete data/media.db, restart and re-scan.
Always wait for Stage 1 done before fetching metadata.

---

## Roadmap

- Gemini AI recommendations
- Automatic provider scoring
- Scheduled scans
- Watchlists
- Multi-user support

---

## License

MIT License

---

## Credits

Built with FastAPI, HTMX, SQLite, TMDB API, and python-telegram-bot.
