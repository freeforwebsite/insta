import os
import re
import sys
import uuid
import time
import shutil
import zipfile
import urllib.parse
import datetime
import asyncio
import logging
from typing import List, Dict, Optional

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.constants import ParseMode, ChatAction
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    InlineQueryHandler,
    ContextTypes,
    filters,
)

import yt_dlp

from database import init_db, get_cached_song, save_cached_song, log_user, _mongo_db
from spotify_helper import (
    detect_platform,
    fetch_universal_metadata,
    fetch_more_artist_songs,
    download_song,
    upload_cloud_file,
)

# Setup logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN")
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "").strip()

DUMP_CHANNEL_RAW = os.getenv("DUMP_CHANNEL_ID", "").strip()
if DUMP_CHANNEL_RAW.startswith("-") and DUMP_CHANNEL_RAW[1:].isdigit():
    DUMP_CHANNEL_ID = int(DUMP_CHANNEL_RAW)
elif DUMP_CHANNEL_RAW.isdigit():
    DUMP_CHANNEL_ID = int(DUMP_CHANNEL_RAW)
else:
    DUMP_CHANNEL_ID = DUMP_CHANNEL_RAW

TEMP_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "downloads")
os.makedirs(TEMP_BASE_DIR, exist_ok=True)

MAX_TELEGRAM_FILE_BYTES = 48 * 1024 * 1024  # 48 MB safety margin for direct Telegram upload


def sanitize_filename(name: str) -> str:
    """Removes invalid characters for filenames."""
    return re.sub(r'[\\/*?:"<>|]', "", name).strip() or "cineprime_music"


def create_zip_archive(files: List[str], base_name: str, output_dir: str) -> Optional[str]:
    """Compresses all files into a single zip archive with CinePrime branding for cloud delivery."""
    if not files:
        return None
    safe_name = sanitize_filename(base_name)
    zip_path = os.path.join(output_dir, f"{safe_name}.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # Add CinePrime Brand Shortcuts and Info file
        z.writestr(
            "Join CinePrime Channel.url",
            "[InternetShortcut]\nURL=https://t.me/cineprimehub\nIconIndex=0\n",
        )
        z.writestr(
            "CinePrime Music Bot.url",
            "[InternetShortcut]\nURL=https://t.me/CinePrimeMusicBot\nIconIndex=0\n",
        )
        z.writestr(
            "About CinePrime Music.txt",
            "==================================================\n"
            "            🎧 CINEPRIME MUSIC HUB 🎧              \n"
            "==================================================\n\n"
            "Official Telegram Channel : https://t.me/cineprimehub\n"
            "Official Music Downloader : https://t.me/CinePrimeMusicBot\n\n"
            "Thank you for choosing CinePrime Music!\n"
            "• Studio Master 320kbps Audio\n"
            "• Clean Embedded ID3 Tags & Album Cover Art\n"
            "• High-Speed Cloud Downloads\n\n"
            "Join @cineprimehub for daily song releases, playlists & requests!\n"
            "==================================================\n"
        )

        for file_path in files:
            if os.path.exists(file_path):
                base = os.path.basename(file_path)
                # Strip any leading numbers like 01_, 02., 03 -
                clean_base = re.sub(r"^\d+[\s._-]+", "", base).strip()
                name, ext = os.path.splitext(clean_base)
                branded_name = f"{name} @CinePrimeMusicBot{ext}" if "@CinePrimeMusicBot" not in clean_base else clean_base
                z.write(file_path, arcname=branded_name)
    return zip_path if os.path.exists(zip_path) else None


def format_circle_progress(percent: float, frame_idx: int = 0) -> str:
    """Returns a rotating circle gauge with percentage and bar."""
    circle_frames = ["◐", "◓", "◑", "◒", "◔", "◕", "◖", "◗"]
    symbol = circle_frames[frame_idx % len(circle_frames)]
    filled = max(0, min(10, int(percent / 10)))
    bar = "▰" * filled + "▱" * (10 - filled)
    return f"{symbol} `[{bar}]` *{percent:.1f}%*"


def format_bytes(b: float) -> str:
    """Formats bytes into human readable size."""
    if not b or b <= 0:
        return "0.0 MB"
    mb = b / (1024 * 1024)
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB"
    return f"{mb:.1f} MB"


def format_time(seconds: float) -> str:
    """Formats seconds into readable string."""
    if not seconds or seconds < 0:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


async def safe_edit_message(msg, text: str, parse_mode=ParseMode.MARKDOWN):
    """Safely edits a Telegram message, suppressing rate limit and identical content errors."""
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except Exception:
        pass


def render_download_card(
    title: str,
    artist: str,
    percent: float,
    downloaded_bytes: float = 0,
    total_bytes: float = 0,
    speed_bytes: float = 0,
    eta_seconds: float = 0,
    elapsed_seconds: float = 0,
    platform: str = "Spotify",
    quality: str = "320",
    status_label: str = "Downloading...",
    spinner_idx: int = 0,
    is_batch: bool = False,
    current_idx: int = 1,
    total_idx: int = 1,
) -> str:
    """Renders the clean, compact CinePrime Music Download Engine card with normal rotating loader."""
    circle_frames = ["◐", "◓", "◑", "◒", "◔", "◕", "◖", "◗"]
    spinner = circle_frames[spinner_idx % len(circle_frames)]
    filled = max(0, min(10, int(percent / 10)))
    bar = "▰" * filled + "▱" * (10 - filled)

    header_title = "BATCH DOWNLOAD ENGINE" if is_batch else "MUSIC DOWNLOAD ENGINE"
    display_status = f"Downloading ({current_idx}/{total_idx})..." if is_batch else status_label

    card = (
        f"╭━━━ 🎧 {header_title} ━━━╮\n\n"
        f"🎵 *{title}*\n"
        f"👤 Artist: *{artist}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{spinner} `[{bar}]` *{percent:.1f}%*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚙️ *ENGINE STATUS*\n\n"
        f"• Source     : `{platform.capitalize()}`\n"
        f"• Downloader : `yt-dlp`\n"
        f"• Processor  : `FFmpeg`\n"
        f"• Format     : `MP3`\n"
        f"• Quality    : `{quality} kbps`\n"
        f"• Status     : `{display_status}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚖️ *LEGAL DISCLAIMER*\n"
        f"• We do not store or host copyrighted media.\n"
        f"• All audio is streamed from public online sources.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"       *Powered by @CinePrimeMusicBot*\n"
        f"╰━━━━━━━━━━━━━━━━━━━━━━━━╯"
    )
    return card


async def check_channel_subscription(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verifies if the user is subscribed to the required channel."""
    if not FORCE_SUB_CHANNEL:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
        return False
    except Exception as e:
        logger.warning(f"Force-sub check warning: {e}")
        return True


def get_force_sub_keyboard() -> InlineKeyboardMarkup:
    """Returns the force subscription buttons."""
    clean_channel = FORCE_SUB_CHANNEL.replace("@", "")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Our Channel", url=f"https://t.me/{clean_channel}")],
        [InlineKeyboardButton("🔄 I Have Joined / Continue", callback_data="check_sub")]
    ])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clean, friendly user welcome message with zero technical jargon."""
    user = update.effective_user
    first_name = user.first_name if user else "Friend"

    if user:
        log_user(user.id, user.first_name, user.username or "")

    if user and not await check_channel_subscription(user.id, context):
        sub_text = (
            f"👋 *வணக்கம் {first_name}!* \n\n"
            f"பாட்டை பதிவிறக்கம் செய்ய, தயவுசெய்து எங்கள் சேனலில் இணையுங்கள்:\n"
            f"👉 *{FORCE_SUB_CHANNEL}*\n\n"
            f"_சேனலில் இணைந்த பிறகு 'I Have Joined' பட்டனை அழுத்தவும்._"
        )
        await update.message.reply_text(sub_text, reply_markup=get_force_sub_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    welcome_text = (
        f"🎧 *Hello {first_name}! Welcome to CinePrime Music Bot!*\n\n"
        "Send me any song, playlist, or album link to download high-quality audio directly to your chat:\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🎵 *Supported Apps:*\n"
        "• 🟢 *Spotify* • 🔴 *YouTube Music* • 🍏 *Apple Music*\n"
        "• 🎵 *JioSaavn* • 🎶 *Wynk Music* • 🟠 *SoundCloud*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✨ *Features:*\n"
        "• ⚡ *Ultra Fast:* Instant high-speed downloads\n"
        "• 🎚️ *Audio Quality:* Choose between 128k, 192k (HQ), or 320k (Lossless)\n"
        "• 📦 *Format Choices:* Download as **Single Songs** or full **ZIP Archive**\n"
        "• 🖼️ *Cover Art:* High resolution artwork embedded in every song\n"
        "• 🔍 *Inline Search:* Type `@CinePrimeMusicBot <song>` anywhere to share music\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚖️ *Legal Disclaimer:* We do not host or store any copyrighted files on our servers. All media streams are fetched dynamically from public third-party online sources. Read /disclaimer for details.\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👉 *Paste any music link below to get started!*"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def disclaimer_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows copyright and content source disclaimer."""
    disclaimer_text = (
        "⚖️ *Copyright & Content Disclaimer*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "• 🚫 *Zero Hosting Policy:*\n"
        "@CinePrimeMusicBot does **NOT** host, upload, or store any copyrighted audio or media files on its servers or databases. All databases only store reference indexes and message pointers.\n\n"
        "• 🌐 *Third-Party Public Sources:*\n"
        "This bot functions strictly as an automated search tool and metadata parser. All audio tracks delivered are fetched on-the-fly directly from publicly accessible third-party online platforms on the internet (such as YouTube, SoundCloud, and open streaming endpoints).\n\n"
        "• 👑 *Intellectual Property Rights:*\n"
        "All music, lyrics, artist likenesses, and album artworks remain the sole intellectual property of their respective copyright owners, record labels, and content creators.\n\n"
        "• 📚 *Fair Use & Non-Commercial Notice:*\n"
        "This bot is intended strictly for personal, private archival, and educational fair-use purposes.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "📩 _For copyright questions, DMCA inquiries, or takedown requests, please contact the originating content hosting platform directly._"
    )
    await update.message.reply_text(disclaimer_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User help guide."""
    help_text = (
        "💡 *CinePrime Music Bot Guide:*\n\n"
        "1️⃣ Copy any music link from Spotify, YouTube, Apple Music, JioSaavn, or Wynk.\n"
        "2️⃣ Paste the link into this chat.\n"
        "3️⃣ Choose your track count and audio quality.\n"
        "4️⃣ Tap **📦 ZIP File** or **🎵 Single Songs**.\n\n"
        "⚡ _Pro Tip: Type `@CinePrimeMusicBot <song>` in any Telegram chat to instantly search and share songs!_\n\n"
        "⚖️ Type /disclaimer to read our copyright & non-hosting legal policy."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only stats dashboard showing MongoDB counts and system status."""
    user = update.effective_user
    if user:
        log_user(user.id, user.first_name, user.username or "")

    user_count = 0
    song_count = 0
    if _mongo_db is not None:
        try:
            user_count = _mongo_db.users.count_documents({})
            song_count = _mongo_db.cached_songs.count_documents({})
        except Exception:
            pass

    stats_text = (
        f"📊 *CinePrime Music Bot — Admin Dashboard*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Registered Users:* `{user_count}`\n"
        f"🎵 *Total Songs in MongoDB:* `{song_count}`\n"
        f"🗄️ *Database Group:* `{DUMP_CHANNEL_ID}`\n"
        f"📢 *Force Sub Channel:* `{FORCE_SUB_CHANNEL}`\n"
        f"☁️ *Cloud Primary:* `Gofile.io (Active)`\n"
        f"🐱 *Cloud Failover:* `Catbox.moe (Ready)`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ _All systems operational._"
    )
    await update.message.reply_text(stats_text, parse_mode=ParseMode.MARKDOWN)


def build_count_keyboard(
    session_id: str,
    total_tracks: int,
    current_lang: Optional[str] = None,
    current_quality: str = "192"
) -> InlineKeyboardMarkup:
    """Builds Step 1 keyboard: Song count, language, and audio quality buttons."""
    buttons = []
    row1 = []
    if total_tracks >= 5:
        row1.append(InlineKeyboardButton("🎵 Top 5", callback_data=f"cnt_{session_id}_5"))
    if total_tracks >= 10:
        row1.append(InlineKeyboardButton("🎵 Top 10", callback_data=f"cnt_{session_id}_10"))
    if row1:
        buttons.append(row1)

    row2 = []
    if total_tracks >= 20:
        row2.append(InlineKeyboardButton("🎵 Top 20", callback_data=f"cnt_{session_id}_20"))
    if total_tracks >= 30:
        row2.append(InlineKeyboardButton("🎵 Top 30", callback_data=f"cnt_{session_id}_30"))
    if row2:
        buttons.append(row2)

    buttons.append([InlineKeyboardButton(f"🎶 All ({total_tracks} Songs)", callback_data=f"cnt_{session_id}_all")])

    # Audio quality row
    q128 = "⚡ 128k" + (" ✅" if current_quality == "128" else "")
    q192 = "🎧 192k" + (" ✅" if current_quality == "192" else "")
    q320 = "💎 320k" + (" ✅" if current_quality == "320" else "")
    buttons.append([
        InlineKeyboardButton(q128, callback_data=f"setq_{session_id}_128"),
        InlineKeyboardButton(q192, callback_data=f"setq_{session_id}_192"),
        InlineKeyboardButton(q320, callback_data=f"setq_{session_id}_320"),
    ])

    lang_display = f"🌐 Language: {current_lang.capitalize() if current_lang else 'All'}"
    buttons.append([InlineKeyboardButton(lang_display, callback_data=f"langmenu_{session_id}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{session_id}")])
    return InlineKeyboardMarkup(buttons)


def build_language_keyboard(session_id: str) -> InlineKeyboardMarkup:
    """Builds language selection button menu."""
    buttons = [
        [
            InlineKeyboardButton("🌐 All Languages", callback_data=f"setlang_{session_id}_all"),
            InlineKeyboardButton("🇮🇳 Tamil", callback_data=f"setlang_{session_id}_tamil"),
        ],
        [
            InlineKeyboardButton("🇮🇳 Telugu", callback_data=f"setlang_{session_id}_telugu"),
            InlineKeyboardButton("🇮🇳 Hindi", callback_data=f"setlang_{session_id}_hindi"),
        ],
        [
            InlineKeyboardButton("🇮🇳 Malayalam", callback_data=f"setlang_{session_id}_malayalam"),
            InlineKeyboardButton("🌐 English", callback_data=f"setlang_{session_id}_english"),
        ],
        [InlineKeyboardButton("⬅️ Back to Song Selection", callback_data=f"back_{session_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_delivery_keyboard(session_id: str, count: int) -> InlineKeyboardMarkup:
    """Builds Step 2 keyboard: Clean two-format button options."""
    buttons = [
        [InlineKeyboardButton("📦 Download as ZIP File", callback_data=f"fmt_{session_id}_{count}_zip")],
        [InlineKeyboardButton("🎵 Download Single Songs (One by One)", callback_data=f"fmt_{session_id}_{count}_single")],
        [
            InlineKeyboardButton("⬅️ Back", callback_data=f"back_{session_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{session_id}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles incoming links from all music platforms."""
    user = update.effective_user
    text = update.message.text.strip()

    if user:
        log_user(user.id, user.first_name, user.username or "")

    if user and not await check_channel_subscription(user.id, context):
        sub_text = (
            f"👋 *வணக்கம் {user.first_name}!* \n\n"
            f"பாட்டை பதிவிறக்கம் செய்ய, தயவுசெய்து எங்கள் சேனலில் இணையுங்கள்:\n"
            f"👉 *{FORCE_SUB_CHANNEL}*\n\n"
            f"_சேனலில் இணைந்த பிறகு 'I Have Joined' பட்டனை அழுத்தவும்._"
        )
        await update.message.reply_text(sub_text, reply_markup=get_force_sub_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return

    platform = detect_platform(text)
    if platform == "unknown" and not (text.startswith("http://") or text.startswith("https://")):
        hint_text = (
            "👋 *Send me any music link to download!*\n\n"
            "Supported Apps:\n"
            "• 🟢 *Spotify:* `https://open.spotify.com/...`\n"
            "• 🔴 *YouTube:* `https://music.youtube.com/...`\n"
            "• 🍏 *Apple Music:* `https://music.apple.com/...`\n"
            "• 🎵 *JioSaavn:* `https://www.jiosaavn.com/...`\n"
            "• 🎶 *Wynk Music:* `https://wynk.in/...`\n"
            "• 🟠 *SoundCloud:* `https://soundcloud.com/...`\n\n"
            "_Send a link or type /start for instructions._"
        )
        await update.message.reply_text(hint_text, parse_mode=ParseMode.MARKDOWN)
        return

    status_msg = await update.message.reply_text(f"🔍 *Fetching song details...*", parse_mode=ParseMode.MARKDOWN)

    # Fetch metadata in worker thread
    metadata = await asyncio.to_thread(fetch_universal_metadata, text)

    if not metadata or not metadata.get("tracks"):
        await status_msg.edit_text(
            "❌ *Failed to fetch details for this music link.*\n"
            "Please verify the URL is public and try again.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    tracks = metadata["tracks"]
    title = metadata.get("title", "Unknown Music Item")
    thumbnail_url = metadata.get("thumbnail_url")
    item_type = metadata.get("type", "track")

    if item_type == "track" and len(tracks) == 1:
        track = tracks[0]
        track["thumbnail_url"] = track.get("thumbnail_url") or thumbnail_url
        await process_single_track(update.message, status_msg, track, context=context, platform=platform)
    else:
        session_id = str(uuid.uuid4())[:8]
        context.user_data[session_id] = {
            "title": title,
            "type": item_type,
            "tracks": tracks,
            "url": text,
            "thumbnail_url": thumbnail_url,
            "language": "all",
            "quality": "192",
            "platform": platform,
        }

        total_tracks = len(tracks)

        # Build preview of first 4 songs
        preview_lines = []
        for i, t in enumerate(tracks[:4], start=1):
            preview_lines.append(f"`{i}.` {t.get('title')} - _{t.get('artist')}_")
        if total_tracks > 4:
            preview_lines.append(f"_...and {total_tracks - 4} more songs_")
        preview_text = "\n".join(preview_lines)

        caption = (
            f"🎶 *{item_type.upper()}:* `{title}`\n"
            f"📊 *Total Tracks:* `{total_tracks}`\n\n"
            f"📜 *Preview:*\n{preview_text}\n\n"
            f"👇 *Step 1: Select how many songs & audio quality:*"
        )

        keyboard = build_count_keyboard(session_id, total_tracks, current_lang="all", current_quality="192")

        if thumbnail_url:
            try:
                await status_msg.delete()
                await update.message.reply_photo(
                    photo=thumbnail_url,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return
            except Exception as e:
                logger.warning(f"Failed to send thumbnail photo: {e}")

        await status_msg.edit_text(caption, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)


async def send_to_database_channel(
    bot,
    audio,
    song_title: str,
    artist: str,
    quality: str,
    query: str,
    platform: str,
    filename: Optional[str] = None,
    duration: int = 0,
    movie: Optional[str] = None,
) -> Optional[int]:
    """
    Sends fresh song to the Database Channel (Strictly no duplicates).
    Uses the exact user-specified CinePrime format:
    🎵 **{Song Title}** ❤️
    🎬 Movie: {Movie}
    🎼 Composer: {Composer}
    🎧 Quality: {Quality} kbps | MP3
    📀 CinePrimeMusic 🎶
    """
    if not DUMP_CHANNEL_ID:
        return None

    try:
        movie_title = movie or "CinePrime Hits"
        caption = (
            f"🎵 **{song_title}** ❤️\n"
            f"🎬 Movie: {movie_title}\n"
            f"🎼 Composer: {artist}\n"
            f"🎧 Quality: {quality} kbps | MP3\n"
            f"📀 CinePrimeMusic 🎶"
        )
        msg = await bot.send_audio(
            chat_id=DUMP_CHANNEL_ID,
            audio=audio,
            filename=filename,
            title=song_title,
            performer=artist,
            duration=duration,
            caption=caption,
            parse_mode=ParseMode.MARKDOWN,
            read_timeout=120,
            write_timeout=300,
        )
        logger.info(f"Posted to Database Channel: msg_id {msg.message_id}")
        return msg.message_id
    except Exception as e:
        logger.warning(f"Failed posting to database channel: {e}")
        return None


async def process_single_track(
    message,
    status_msg,
    track: Dict,
    quality: str = "192",
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    platform: str = "music"
):
    """Downloads and sends a single track with clean user captions."""
    song_title = track.get("title", "Unknown Song")
    artist = track.get("artist", "Unknown Artist")
    query = track.get("url") or f"{artist} - {song_title}"
    thumb_url = track.get("thumbnail_url")
    bot = context.bot if context else message._bot

    # 1. Check Cache
    cached = get_cached_song(query, quality)
    if cached:
        try:
            await status_msg.edit_text("⚡ *Sending audio...*", parse_mode=ParseMode.MARKDOWN)
            user_caption = (
                f"🎵 **{cached['title']}** ❤️\n"
                f"🎬 Movie: {cached.get('album') or 'CinePrime Hits'}\n"
                f"🎼 Composer: {cached['artist']}\n"
                f"🎧 Quality: {quality} kbps | MP3\n"
                f"📀 CinePrimeMusic 🎶"
            )
            await message.reply_audio(
                audio=cached["file_id"],
                title=cached["title"],
                performer=cached["artist"],
                duration=cached["duration"],
                caption=user_caption,
                parse_mode=ParseMode.MARKDOWN,
            )
            await status_msg.delete()
            return
        except Exception as e:
            logger.warning(f"Cached send failed, falling back to fresh download: {e}")

    # 2. Fresh download with Live CinePrime Ultra-Engine
    start_time = time.time()
    init_card = render_download_card(
        title=song_title,
        artist=artist,
        percent=0.0,
        downloaded_bytes=0,
        total_bytes=0,
        speed_bytes=0,
        eta_seconds=0,
        elapsed_seconds=0,
        platform=platform,
        quality=quality,
        status_label="Connecting...",
        spinner_idx=0,
    )
    await safe_edit_message(status_msg, init_card)
    await message.chat.send_action(ChatAction.UPLOAD_VOICE)

    loop = asyncio.get_running_loop()
    last_edit = [0.0]
    spinner_idx = [0]

    def on_progress(d):
        now = time.time()
        if now - last_edit[0] < 1.8:
            return
        last_edit[0] = now
        status = d.get("status")
        elapsed = now - start_time
        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            pct = (downloaded / total * 100) if total else 0
            spinner_idx[0] += 1
            card = render_download_card(
                title=song_title,
                artist=artist,
                percent=pct,
                downloaded_bytes=downloaded,
                total_bytes=total,
                speed_bytes=speed,
                eta_seconds=eta,
                elapsed_seconds=elapsed,
                platform=platform,
                quality=quality,
                status_label="Downloading...",
                spinner_idx=spinner_idx[0],
            )
            asyncio.run_coroutine_threadsafe(safe_edit_message(status_msg, card), loop)
        elif status == "finished":
            total_b = d.get("total_bytes") or d.get("downloaded_bytes") or 0
            card = render_download_card(
                title=song_title,
                artist=artist,
                percent=100.0,
                downloaded_bytes=total_b,
                total_bytes=total_b,
                speed_bytes=0,
                eta_seconds=0,
                elapsed_seconds=elapsed,
                platform=platform,
                quality=quality,
                status_label="Processing FFmpeg...",
                spinner_idx=spinner_idx[0],
            )
            asyncio.run_coroutine_threadsafe(safe_edit_message(status_msg, card), loop)

    temp_folder = os.path.join(TEMP_BASE_DIR, str(uuid.uuid4()))
    try:
        mp3_path = await asyncio.to_thread(
            download_song,
            query=query,
            output_dir=temp_folder,
            quality=quality,
            thumbnail_url=thumb_url,
            title=song_title,
            artist=artist,
            album=track.get("album") or "CinePrime Music",
            progress_callback=on_progress,
        )

        if not mp3_path or not os.path.exists(mp3_path):
            await status_msg.edit_text(f"❌ Could not download `{song_title}`. Audio source not found.", parse_mode=ParseMode.MARKDOWN)
            return

        await status_msg.edit_text("📤 *Uploading audio to Telegram...*", parse_mode=ParseMode.MARKDOWN)

        movie_title = track.get("album") or track.get("movie") or "CinePrime Hits"
        user_caption = (
            f"🎵 **{song_title}** ❤️\n"
            f"🎬 Movie: {movie_title}\n"
            f"🎼 Composer: {artist}\n"
            f"🎧 Quality: {quality} kbps | MP3\n"
            f"📀 CinePrimeMusic 🎶"
        )
        base_name = os.path.basename(mp3_path)
        with open(mp3_path, "rb") as audio_file:
            sent_audio = await message.reply_audio(
                audio=audio_file,
                filename=base_name,
                title=song_title,
                performer=artist,
                duration=track.get("duration", 0),
                caption=user_caption,
                parse_mode=ParseMode.MARKDOWN,
                read_timeout=120,
                write_timeout=300,
            )

        if sent_audio and sent_audio.audio:
            file_id = sent_audio.audio.file_id

            # Send ONE copy to Database Channel (Strictly no duplicates)
            channel_msg_id = await send_to_database_channel(
                bot, file_id, song_title, artist, quality, query, platform, filename=base_name, duration=track.get("duration", 0), movie=movie_title
            )

            # Save in MongoDB
            save_cached_song(
                query=query,
                file_id=file_id,
                title=song_title,
                artist=artist,
                duration=track.get("duration", 0),
                quality=quality,
                channel_message_id=channel_msg_id,
                channel_id=str(DUMP_CHANNEL_ID) if DUMP_CHANNEL_ID else None,
            )

        await status_msg.delete()

    except Exception as e:
        logger.error(f"Error handling track {query}: {e}")
        await status_msg.edit_text(f"⚠️ Error sending track: {e}")
    finally:
        if os.path.exists(temp_folder):
            shutil.rmtree(temp_folder, ignore_errors=True)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all interactive button clicks."""
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    if user:
        log_user(user.id, user.first_name, user.username or "")

    data = query.data

    if data == "check_sub":
        if await check_channel_subscription(user.id, context):
            await query.edit_message_text("✅ *நன்றி! நீங்கள் எங்கள் சேனலில் இணைந்துவிட்டீர்கள்.* இப்போது நீங்கள் எந்த பாடல் லிங்கையும் அனுப்பலாம்.")
        else:
            await query.answer("⚠️ நீங்கள் இன்னும் சேனலில் இணையவில்லை. தயவுசெய்து இணையவும்!", show_alert=True)
        return

    if data.startswith("cancel_"):
        await query.edit_message_caption("❌ Download cancelled.") if query.message.caption else await query.edit_message_text("❌ Download cancelled.")
        return

    # Quality toggle
    if data.startswith("setq_"):
        parts = data.split("_")
        session_id = parts[1]
        chosen_quality = parts[2]

        session_data = context.user_data.get(session_id)
        if not session_data:
            await edit_msg(query, "⚠️ Session expired. Please send the link again.")
            return

        session_data["quality"] = chosen_quality
        total_tracks = len(session_data["tracks"])
        current_lang = session_data.get("language", "all")
        caption = (
            f"🎶 *{session_data['type'].upper()}:* `{session_data['title']}`\n"
            f"🎧 *Selected Audio Quality:* `{chosen_quality} kbps`\n"
            f"📊 *Total Tracks:* `{total_tracks}`\n\n"
            f"👇 *Step 1: Select how many songs & audio quality:*"
        )
        keyboard = build_count_keyboard(session_id, total_tracks, current_lang=current_lang, current_quality=chosen_quality)
        await edit_msg(query, caption, keyboard)
        return

    # Language menu toggle
    if data.startswith("langmenu_"):
        session_id = data.split("_")[1]
        caption = "🌐 *Select Language Filter:*\n_Choose a language from the buttons below:_"
        await edit_msg(query, caption, build_language_keyboard(session_id))
        return

    # Set language
    if data.startswith("setlang_"):
        parts = data.split("_")
        session_id = parts[1]
        chosen_lang = parts[2]

        session_data = context.user_data.get(session_id)
        if not session_data:
            await edit_msg(query, "⚠️ Session expired. Please send the link again.")
            return

        session_data["language"] = chosen_lang
        total_tracks = len(session_data["tracks"])
        quality = session_data.get("quality", "192")
        caption = (
            f"🎶 *{session_data['type'].upper()}:* `{session_data['title']}`\n"
            f"🌐 *Language Filter:* `{chosen_lang.capitalize()}`\n"
            f"📊 *Total Tracks:* `{total_tracks}`\n\n"
            f"👇 *Step 1: Select how many songs & audio quality:*"
        )
        keyboard = build_count_keyboard(session_id, total_tracks, current_lang=chosen_lang, current_quality=quality)
        await edit_msg(query, caption, keyboard)
        return

    # Back to step 1
    if data.startswith("back_"):
        session_id = data.split("_")[1]
        session_data = context.user_data.get(session_id)
        if not session_data:
            await edit_msg(query, "⚠️ Session expired. Please send the link again.")
            return
        total_tracks = len(session_data["tracks"])
        current_lang = session_data.get("language", "all")
        quality = session_data.get("quality", "192")
        caption = (
            f"🎶 *{session_data['type'].upper()}:* `{session_data['title']}`\n"
            f"🌐 *Language:* `{current_lang.capitalize()}`\n"
            f"📊 *Total Tracks:* `{total_tracks}`\n\n"
            f"👇 *Step 1: Select how many songs & audio quality:*"
        )
        keyboard = build_count_keyboard(session_id, total_tracks, current_lang=current_lang, current_quality=quality)
        await edit_msg(query, caption, keyboard)
        return

    # Step 1: Song count selected -> Step 2: Choose delivery format
    if data.startswith("cnt_"):
        parts = data.split("_")
        session_id = parts[1]
        count_choice = parts[2]

        session_data = context.user_data.get(session_id)
        if not session_data:
            await edit_msg(query, "⚠️ Session expired. Please send the link again.")
            return

        total_tracks = len(session_data["tracks"])
        selected_count = total_tracks if count_choice == "all" else min(int(count_choice), total_tracks)

        current_lang = session_data.get("language", "all")
        quality = session_data.get("quality", "192")
        caption = (
            f"🎶 *{session_data['type'].upper()}:* `{session_data['title']}`\n"
            f"✅ *Selected Songs:* `{selected_count}`\n"
            f"🎧 *Audio Quality:* `{quality} kbps`\n"
            f"🌐 *Language:* `{current_lang.capitalize()}`\n\n"
            f"📦 *Step 2: Choose Format:*\n"
            f"Tap a button below to choose how you want to receive your songs:"
        )
        keyboard = build_delivery_keyboard(session_id, selected_count)
        await edit_msg(query, caption, keyboard)
        return

    # Step 2: Format selected ('zip' or 'single') -> Execute download
    if data.startswith("fmt_"):
        parts = data.split("_")
        session_id = parts[1]
        target_count = int(parts[2])
        mode = parts[3]

        session_data = context.user_data.get(session_id)
        if not session_data:
            await edit_msg(query, "⚠️ Session expired. Please send the link again.")
            return

        tracks_to_download = session_data["tracks"][:target_count]
        playlist_title = session_data["title"]
        language = session_data.get("language", "all")
        quality = session_data.get("quality", "192")
        item_type = session_data.get("type", "playlist")
        thumb_url = session_data.get("thumbnail_url")
        platform = session_data.get("platform", "music")

        if item_type == "artist" and target_count > len(tracks_to_download):
            extra_songs = await asyncio.to_thread(fetch_more_artist_songs, playlist_title, language, target_count)
            if extra_songs:
                tracks_to_download = extra_songs[:target_count]

        if mode == "zip":
            await run_zip_delivery(query, playlist_title, tracks_to_download, language, quality, thumb_url, platform)
        else:
            await run_single_delivery(query, playlist_title, tracks_to_download, language, quality, thumb_url, context, platform)

        context.user_data.pop(session_id, None)


async def edit_msg(query, text: str, reply_markup=None):
    """Helper to edit either caption or text depending on message type."""
    try:
        if query.message.caption:
            await query.edit_message_caption(caption=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.warning(f"Error editing message: {e}")


async def run_zip_delivery(
    query,
    title: str,
    tracks: List[Dict],
    language: Optional[str] = None,
    quality: str = "192",
    thumb_url: Optional[str] = None,
    platform: str = "music"
):
    """Downloads songs, packages into ZIP archive, and uploads to Cloud with failover."""
    target_count = len(tracks)
    await edit_msg(
        query,
        f"📦 *Preparing ZIP File ({quality}kbps) for {target_count} songs from* `{title}`...\n\n"
        f"⚖️ *Disclaimer:* We do not host or store copyrighted media. All audio is fetched from public online sources for personal fair-use.",
    )

    temp_folder = os.path.join(TEMP_BASE_DIR, f"zip_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_folder, exist_ok=True)

    progress_msg = await query.message.reply_text(f"⏳ Starting CinePrime Batch Engine for {target_count} songs...")
    downloaded_files = []
    start_batch_time = time.time()

    for i, track in enumerate(tracks, start=1):
        song_title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        query_text = track.get("url") or f"{artist} - {song_title}"

        elapsed = time.time() - start_batch_time
        avg_per_song = (elapsed / (i - 1)) if i > 1 else 6.0
        rem_songs = target_count - (i - 1)
        eta_batch = avg_per_song * rem_songs
        batch_pct = ((i - 1) / target_count) * 100
        circle = format_circle_progress(batch_pct, i)
        collected_bytes = sum(os.path.getsize(f) for f in downloaded_files if os.path.exists(f))

        card = render_download_card(
            title=song_title,
            artist=artist,
            percent=batch_pct,
            downloaded_bytes=collected_bytes,
            total_bytes=collected_bytes * (target_count / i) if i > 0 else 0,
            speed_bytes=0,
            eta_seconds=eta_batch,
            elapsed_seconds=elapsed,
            platform=platform,
            quality=quality,
            status_label=f"Batch Track {i}/{target_count}",
            spinner_idx=i,
            is_batch=True,
            current_idx=i,
            total_idx=target_count,
        )
        try:
            await safe_edit_message(progress_msg, card)

            loop = asyncio.get_running_loop()
            last_inner = [0.0]

            def on_inner(d):
                now = time.time()
                if now - last_inner[0] < 2.0:
                    return
                last_inner[0] = now
                if d.get("status") == "downloading":
                    speed = d.get("speed") or 0
                    cur_dl = d.get("downloaded_bytes", 0)
                    cur_tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    pct = (cur_dl / cur_tot * 100) if cur_tot else batch_pct
                    inner_card = render_download_card(
                        title=song_title,
                        artist=artist,
                        percent=pct,
                        downloaded_bytes=collected_bytes + cur_dl,
                        total_bytes=collected_bytes * (target_count / i) if i > 0 else cur_tot,
                        speed_bytes=speed,
                        eta_seconds=eta_batch,
                        elapsed_seconds=now - start_batch_time,
                        platform=platform,
                        quality=quality,
                        status_label=f"Streaming Track {i}/{target_count}",
                        spinner_idx=i + int(now) % 8,
                        is_batch=True,
                        current_idx=i,
                        total_idx=target_count,
                    )
                    asyncio.run_coroutine_threadsafe(safe_edit_message(progress_msg, inner_card), loop)

            mp3_path = await asyncio.to_thread(
                download_song,
                query=query_text,
                output_dir=temp_folder,
                filename_prefix="",
                language=language,
                quality=quality,
                thumbnail_url=track.get("thumbnail_url") or thumb_url,
                title=song_title,
                artist=artist,
                album=title,
                progress_callback=on_inner,
            )
            if mp3_path and os.path.exists(mp3_path):
                downloaded_files.append(mp3_path)

                # Upload each song individually to Dump Channel (-1004177979820)
                if DUMP_CHANNEL_ID:
                    cached_check = get_cached_song(query_text, quality)
                    try:
                        base_name = os.path.basename(mp3_path)
                        if cached_check and cached_check.get("file_id"):
                            audio_payload = cached_check["file_id"]
                        else:
                            audio_payload = open(mp3_path, "rb")

                        db_msg = await bot.send_audio(
                            chat_id=DUMP_CHANNEL_ID,
                            audio=audio_payload,
                            filename=base_name,
                            title=song_title,
                            performer=artist,
                            duration=track.get("duration", 0),
                            caption=(
                                f"🎵 **{song_title}** ❤️\n"
                                f"🎬 Movie: {title or 'CinePrime Hits'}\n"
                                f"🎼 Composer: {artist}\n"
                                f"🎧 Quality: {quality} kbps | MP3\n"
                                f"📀 CinePrimeMusic 🎶"
                            ),
                            parse_mode=ParseMode.MARKDOWN,
                            read_timeout=120,
                            write_timeout=300,
                        )
                        if hasattr(audio_payload, "close"):
                            audio_payload.close()

                        if db_msg and db_msg.audio and not cached_check:
                            save_cached_song(
                                query=query_text,
                                file_id=db_msg.audio.file_id,
                                title=song_title,
                                artist=artist,
                                duration=track.get("duration", 0),
                                quality=quality,
                                channel_message_id=db_msg.message_id,
                                channel_id=str(DUMP_CHANNEL_ID),
                            )
                            logger.info(f"Uploaded batch track {i} to dump channel: {song_title}")
                    except Exception as upload_err:
                        logger.warning(f"Failed uploading track {i} to dump channel: {upload_err}")
        except Exception as e:
            logger.error(f"Error downloading {query_text}: {e}")

        await asyncio.sleep(0.3)

    if not downloaded_files:
        await progress_msg.edit_text("❌ No songs could be downloaded to create the ZIP file.")
        shutil.rmtree(temp_folder, ignore_errors=True)
        return

    await progress_msg.edit_text(
        f"🗜️ *Compressing {len(downloaded_files)} songs into ZIP archive...*\n"
        f"☁️ *Uploading to High Speed Cloud Storage...*",
        parse_mode=ParseMode.MARKDOWN,
    )

    zip_file = await asyncio.to_thread(create_zip_archive, downloaded_files, title, temp_folder)

    if not zip_file:
        await progress_msg.edit_text("❌ Failed to create ZIP archive.")
        shutil.rmtree(temp_folder, ignore_errors=True)
        return

    file_size_bytes = os.path.getsize(zip_file)
    size_mb = file_size_bytes / (1024 * 1024)

    cloud_res = await asyncio.to_thread(upload_cloud_file, zip_file, GOFILE_API_TOKEN)
    dl_url = cloud_res.get("url")

    if file_size_bytes <= MAX_TELEGRAM_FILE_BYTES:
        try:
            await query.message.chat.send_action(ChatAction.UPLOAD_DOCUMENT)
            caption = f"📦 *{title}* (ZIP Archive)\n🎵 {len(downloaded_files)} songs | {size_mb:.1f} MB | {quality}kbps"
            with open(zip_file, "rb") as zf:
                await query.message.reply_document(document=zf, filename=os.path.basename(zip_file), caption=caption)
        except Exception as e:
            logger.warning(f"Direct Telegram upload failed: {e}")

    buttons = []
    if dl_url:
        buttons.append([InlineKeyboardButton("⬇️ Download ZIP File", url=dl_url)])
        share_text = urllib.parse.quote(f"🎵 Download {title} ({len(downloaded_files)} songs) ZIP: {dl_url}")
        buttons.append([InlineKeyboardButton("🔗 Share Download Link", url=f"https://t.me/share/url?url={share_text}")])

    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    success_text = (
        f"🎉 *Your Playlist ZIP File is Ready!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎶 *Title:* `{title}`\n"
        f"🎵 *Total Songs:* `{len(downloaded_files)}`\n"
        f"🎧 *Audio Quality:* `{quality} kbps`\n"
        f"📊 *Archive Size:* `{size_mb:.1f} MB`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👇 *Click below for 1-click high speed download:*"
    )
    await progress_msg.edit_text(success_text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    shutil.rmtree(temp_folder, ignore_errors=True)


async def run_single_delivery(
    query,
    title: str,
    tracks: List[Dict],
    language: Optional[str] = None,
    quality: str = "192",
    thumb_url: Optional[str] = None,
    context: Optional[ContextTypes.DEFAULT_TYPE] = None,
    platform: str = "music"
):
    """Downloads and sends songs as single audio files with MongoDB caching & channel archive."""
    target_count = len(tracks)
    await edit_msg(
        query,
        f"🎵 *Starting download for {target_count} songs ({quality}kbps) from* `{title}`...\n\n"
        f"⚖️ *Disclaimer:* We do not host or store copyrighted media. All audio is fetched from public online sources for personal fair-use.",
    )

    temp_folder = os.path.join(TEMP_BASE_DIR, f"single_{uuid.uuid4().hex[:8]}")
    os.makedirs(temp_folder, exist_ok=True)

    sent_count = 0
    failed_count = 0
    progress_msg = await query.message.reply_text("⏳ Initializing audio queue...")
    bot = context.bot if context else query.message._bot

    for i, track in enumerate(tracks, start=1):
        song_title = track.get("title", "Unknown")
        artist = track.get("artist", "Unknown")
        query_text = track.get("url") or f"{artist} - {song_title}"
        t_thumb = track.get("thumbnail_url") or thumb_url

        try:
            # 1. Instant cache lookup
            cached = get_cached_song(query_text, quality)
            if cached:
                user_caption = f"🎵 *{cached['title']}*\n👤 {cached['artist']} ({i}/{target_count})\n🎧 {quality}kbps • @CinePrimeMusicBot"
                await query.message.reply_audio(
                    audio=cached["file_id"],
                    title=cached["title"],
                    performer=cached["artist"],
                    duration=cached["duration"],
                    caption=user_caption,
                    parse_mode=ParseMode.MARKDOWN,
                )
                sent_count += 1
                await asyncio.sleep(0.4)
                continue

            # 2. Fresh download with live engine stats
            single_start = time.time()
            card = render_download_card(
                title=song_title,
                artist=artist,
                percent=((i - 1) / target_count) * 100,
                downloaded_bytes=0,
                total_bytes=0,
                speed_bytes=0,
                eta_seconds=0,
                elapsed_seconds=0,
                platform=platform,
                quality=quality,
                status_label=f"Connecting ({i}/{target_count})...",
                spinner_idx=i,
                is_batch=False,
            )
            await safe_edit_message(progress_msg, card)
            await query.message.chat.send_action(ChatAction.UPLOAD_VOICE)

            loop = asyncio.get_running_loop()
            last_inner = [0.0]

            def on_single_progress(d):
                now = time.time()
                if now - last_inner[0] < 2.0:
                    return
                last_inner[0] = now
                if d.get("status") == "downloading":
                    speed = d.get("speed") or 0
                    cur_dl = d.get("downloaded_bytes", 0)
                    cur_tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    eta = d.get("eta") or 0
                    pct = (cur_dl / cur_tot * 100) if cur_tot else 0
                    inner_card = render_download_card(
                        title=song_title,
                        artist=artist,
                        percent=pct,
                        downloaded_bytes=cur_dl,
                        total_bytes=cur_tot,
                        speed_bytes=speed,
                        eta_seconds=eta,
                        elapsed_seconds=now - single_start,
                        platform=platform,
                        quality=quality,
                        status_label=f"Downloading ({i}/{target_count})...",
                        spinner_idx=i + int(now) % 8,
                        is_batch=False,
                    )
                    asyncio.run_coroutine_threadsafe(safe_edit_message(progress_msg, inner_card), loop)

            mp3_path = await asyncio.to_thread(
                download_song,
                query=query_text,
                output_dir=temp_folder,
                filename_prefix="",
                language=language,
                quality=quality,
                thumbnail_url=t_thumb,
                title=song_title,
                artist=artist,
                progress_callback=on_single_progress,
            )

            if mp3_path and os.path.exists(mp3_path):
                base_name = os.path.basename(mp3_path)
                movie_title = track.get("album") or title or "CinePrime Hits"
                user_caption = (
                    f"🎵 **{song_title}** ❤️\n"
                    f"🎬 Movie: {movie_title}\n"
                    f"🎼 Composer: {artist}\n"
                    f"🎧 Quality: {quality} kbps | MP3\n"
                    f"📀 CinePrimeMusic 🎶"
                )
                with open(mp3_path, "rb") as audio_file:
                    sent = await query.message.reply_audio(
                        audio=audio_file,
                        filename=base_name,
                        title=song_title,
                        performer=artist,
                        duration=track.get("duration", 0),
                        caption=user_caption,
                        parse_mode=ParseMode.MARKDOWN,
                        read_timeout=120,
                        write_timeout=300,
                    )
                sent_count += 1

                # Send ONE copy to Database Channel (Strictly no duplicate)
                if sent and sent.audio:
                    file_id = sent.audio.file_id
                    channel_msg_id = await send_to_database_channel(
                        bot, file_id, song_title, artist, quality, query_text, platform, filename=base_name, duration=track.get("duration", 0), movie=movie_title
                    )

                    # Save in MongoDB
                    save_cached_song(
                        query=query_text,
                        file_id=file_id,
                        title=song_title,
                        artist=artist,
                        duration=track.get("duration", 0),
                        quality=quality,
                        channel_message_id=channel_msg_id,
                        channel_id=str(DUMP_CHANNEL_ID) if DUMP_CHANNEL_ID else None,
                    )

                try:
                    os.remove(mp3_path)
                except Exception:
                    pass
            else:
                failed_count += 1

        except Exception as e:
            logger.error(f"Failed to send track {query_text}: {e}")
            failed_count += 1

        await asyncio.sleep(0.8)

    try:
        await progress_msg.edit_text(
            f"✅ *Finished sending songs:*\n"
            f"🎶 `{title}`\n"
            f"🎉 *Successfully sent:* {sent_count} songs\n"
            f"{f'⚠️ *Failed:* {failed_count} songs' if failed_count > 0 else ''}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass

    shutil.rmtree(temp_folder, ignore_errors=True)


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles inline searches: type @CinePrimeMusicBot <query> anywhere in Telegram!"""
    query = update.inline_query.query.strip()
    if not query:
        return

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
    }

    results = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            search_res = ydl.extract_info(f"ytsearch5:{query} audio", download=False)
            entries = search_res.get("entries", []) if search_res else []

            for idx, entry in enumerate(entries):
                if not entry:
                    continue
                v_title = entry.get("title", "Unknown Title")
                v_url = f"https://www.youtube.com/watch?v={entry.get('id')}"
                v_duration = entry.get("duration") or 0
                mins, secs = divmod(v_duration, 60)
                dur_str = f"{int(mins)}:{int(secs):02d}" if v_duration else "Unknown"

                article = InlineQueryResultArticle(
                    id=str(idx),
                    title=v_title,
                    description=f"⏱️ {dur_str} | Click to download MP3",
                    input_message_content=InputTextMessageContent(v_url),
                )
                results.append(article)

        await update.inline_query.answer(results, cache_time=60)
    except Exception as e:
        logger.warning(f"Inline search error: {e}")


def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        print("ERROR: TELEGRAM_BOT_TOKEN is not set!")
        sys.exit(1)

    # Initialize MongoDB Database
    init_db()

    # Ensure event loop exists for Python 3.14 compatibility
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    print("Starting CinePrime Universal Music Bot...")
    req = HTTPXRequest(read_timeout=120, write_timeout=300, connect_timeout=60)
    app = ApplicationBuilder().token(BOT_TOKEN).request(req).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("disclaimer", disclaimer_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(InlineQueryHandler(handle_inline_query))

    print("Bot is running and polling! Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
