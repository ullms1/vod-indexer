"""
VOD-Indexer Telegram Bot
Communicates exclusively through the VOD-Indexer API.
APPROVAL MODE: user must confirm before any sync.
"""
import os
import asyncio
import httpx
from typing import Optional

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, CallbackQueryHandler,
        MessageHandler, filters, ContextTypes
    )
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
API_BASE = os.environ.get("VOD_INDEXER_API", "http://vod-indexer:3030/api")
ALLOWED_CHAT_IDS_RAW = os.environ.get("ALLOWED_CHAT_IDS", "")
ALLOWED_CHAT_IDS = set(int(x.strip()) for x in ALLOWED_CHAT_IDS_RAW.split(",") if x.strip().isdigit())


async def api_get(path: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{API_BASE}{path}")
        r.raise_for_status()
        return r.json()


async def api_post(path: str, data: dict = {}) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(f"{API_BASE}{path}", json=data)
        r.raise_for_status()
        return r.json()


def is_allowed(update: Update) -> bool:
    if not ALLOWED_CHAT_IDS:
        return True
    return update.effective_chat.id in ALLOWED_CHAT_IDS


def format_media(item: dict) -> str:
    year = f" ({item['year']})" if item.get("year") else ""
    provider = item.get("best_provider", "?")
    status = item.get("status", "available")
    status_icon = "✅" if status == "synced" else "🔵"
    seasons = ""
    if item.get("season_count"):
        seasons = f"\n📺 {item['season_count']} temporadas"
    return (
        f"{status_icon} *{item['title']}*{year}\n"
        f"🏷 Provider: `{provider}`{seasons}\n"
        f"Estado: `{status}`"
    )


# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    await update.message.reply_text(
        "🎬 *VOD-Indexer Bot*\n\n"
        "Comandos disponibles:\n"
        "/search `<título>` — Buscar contenido\n"
        "/recent — Agregados recientemente\n"
        "/selected — Contenido sincronizado\n"
        "/missing — Sin metadata\n"
        "/random — Ítem aleatorio\n"
        "/stats — Estadísticas\n"
        "/sync `<id>` — Sincronizar a Jellyfin",
        parse_mode="Markdown"
    )


async def cmd_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    query = " ".join(ctx.args)
    if not query:
        await update.message.reply_text("Uso: /search <título>")
        return

    try:
        results = await api_get(f"/search?q={query}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    if not results:
        await update.message.reply_text(f"Sin resultados para: *{query}*", parse_mode="Markdown")
        return

    for item in results[:5]:
        text = format_media(item)
        keyboard = [[
            InlineKeyboardButton("▶ Sincronizar", callback_data=f"sync:{item['id']}"),
            InlineKeyboardButton("ℹ Info", callback_data=f"info:{item['id']}"),
        ]]
        await update.message.reply_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def cmd_recent(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        data = await api_get("/media?limit=8")
        items = data.get("items", [])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    if not items:
        await update.message.reply_text("Sin contenido indexado aún.")
        return

    lines = []
    for item in items:
        icon = "✅" if item["status"] == "synced" else "🔵"
        year = f" ({item['year']})" if item.get("year") else ""
        lines.append(f"{icon} *{item['title']}*{year} — `{item.get('best_provider','?')}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_selected(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        data = await api_get("/media?status=synced&limit=10")
        items = data.get("items", [])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    if not items:
        await update.message.reply_text("Nada sincronizado a Jellyfin todavía.")
        return

    total = data.get("total", len(items))
    lines = [f"✅ *Sincronizado en Jellyfin* ({total} total)\n"]
    for item in items[:10]:
        year = f" ({item['year']})" if item.get("year") else ""
        lines.append(f"• {item['title']}{year}")
    if total > 10:
        lines.append(f"_...y {total - 10} más_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_missing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        stats = await api_get("/stats")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    await update.message.reply_text(
        f"📊 *Estado de metadata*\n\n"
        f"Total indexado: `{stats['total']}`\n"
        f"Con metadata: `{stats['with_meta']}`\n"
        f"Sin metadata: `{stats['pending_meta']}`",
        parse_mode="Markdown"
    )


async def cmd_stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        stats = await api_get("/stats")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return

    await update.message.reply_text(
        f"📊 *VOD-Indexer Stats*\n\n"
        f"🎬 Películas: `{stats['movies']}`\n"
        f"📺 Series: `{stats['series']}`\n"
        f"✅ Sincronizados: `{stats['synced']}`\n"
        f"🏷 Providers: `{stats['providers']}`\n"
        f"📚 Colecciones: `{stats['collections']}`\n"
        f"⚠ Sin metadata: `{stats['pending_meta']}`",
        parse_mode="Markdown"
    )


async def cmd_random(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    try:
        data = await api_get("/media?limit=500")
        items = data.get("items", [])
        if not items:
            await update.message.reply_text("Sin contenido.")
            return
        import random
        item = random.choice(items)
        text = format_media(item)
        keyboard = [[
            InlineKeyboardButton("▶ Sincronizar", callback_data=f"sync:{item['id']}"),
        ]]
        await update.message.reply_text(text, parse_mode="Markdown",
                                        reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update):
        return
    if not ctx.args or not ctx.args[0].isdigit():
        await update.message.reply_text("Uso: /sync <id>")
        return
    media_id = int(ctx.args[0])
    keyboard = [[
        InlineKeyboardButton("✅ Confirmar sync", callback_data=f"sync:{media_id}"),
        InlineKeyboardButton("❌ Cancelar", callback_data="cancel"),
    ]]
    await update.message.reply_text(
        f"¿Confirmar sincronización de media ID `{media_id}`?",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ─── Callbacks ────────────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "cancel":
        await query.edit_message_text("Cancelado.")
        return

    if data.startswith("sync:"):
        media_id = int(data.split(":")[1])
        # APPROVAL MODE — show confirmation
        keyboard = [[
            InlineKeyboardButton("✅ Sí, sincronizar", callback_data=f"confirm_sync:{media_id}"),
            InlineKeyboardButton("❌ No", callback_data="cancel"),
        ]]
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
        await query.message.reply_text(
            f"⚠️ *Confirmar:* ¿Sincronizar ID `{media_id}` a Jellyfin?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif data.startswith("confirm_sync:"):
        media_id = int(data.split(":")[1])
        try:
            result = await api_post(f"/media/{media_id}/sync")
            await query.edit_message_text(f"▶ Sincronización iniciada para ID `{media_id}`", parse_mode="Markdown")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")

    elif data.startswith("info:"):
        media_id = int(data.split(":")[1])
        try:
            item = await api_get(f"/media/{media_id}")
            sources_text = "\n".join(
                f"{'⭐' if s['is_best'] else '⚠'} {s['provider']} — {s.get('season_count', 0)}T"
                for s in item.get("sources", [])
            )
            text = (
                f"*{item['title']}* ({item.get('year', '?')})\n\n"
                f"{item.get('overview', 'Sin descripción.')[:300]}\n\n"
                f"*Fuentes:*\n{sources_text or 'Ninguna'}"
            )
            await query.message.reply_text(text, parse_mode="Markdown")
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")


def main():
    if not TELEGRAM_AVAILABLE:
        print("[Bot] python-telegram-bot not installed. Install it to use the bot.")
        return
    if not BOT_TOKEN:
        print("[Bot] TELEGRAM_BOT_TOKEN not set.")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("recent", cmd_recent))
    app.add_handler(CommandHandler("selected", cmd_selected))
    app.add_handler(CommandHandler("missing", cmd_missing))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("random", cmd_random))
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CallbackQueryHandler(handle_callback))

    print("[Bot] Starting VOD-Indexer Telegram Bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
