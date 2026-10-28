import os
import re
import datetime
import logging
from typing import Optional, Dict

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

MONGO_URI = (os.getenv("MONGO_URI", "").strip() or os.getenv("MONGODB_URI", "").strip())
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "cineprime_music_bot").strip()

_mongo_client = None
_mongo_db = None
_use_mongo = False


def init_db():
    """Initializes MongoDB connection and creates indexes."""
    global _mongo_client, _mongo_db, _use_mongo
    if MONGO_URI:
        try:
            import pymongo
            _mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
            _mongo_client.server_info()
            _mongo_db = _mongo_client[MONGO_DB_NAME]
            _use_mongo = True

            # Create Indexes
            _mongo_db.cached_songs.create_index("query_key", unique=True)
            _mongo_db.users.create_index("user_id", unique=True)

            logger.info(f"MongoDB connected successfully to '{MONGO_DB_NAME}'")
            return
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}. Falling back to SQLite.")
            _use_mongo = False

    # SQLite Fallback
    import sqlite3
    conn = sqlite3.connect("music_bot.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cached_songs (
            query_key TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            channel_message_id INTEGER DEFAULT NULL,
            channel_id TEXT DEFAULT NULL,
            title TEXT,
            artist TEXT,
            duration INTEGER,
            quality TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
    logger.info("SQLite database fallback initialized.")


def normalize_key(query: str) -> str:
    """Normalizes search query to maximize cache hits."""
    clean = re.sub(r"[^\w\s]", "", query.lower())
    return " ".join(clean.split())


def log_user(user_id: int, first_name: str = "", username: str = ""):
    """Logs user activity in MongoDB."""
    global _use_mongo, _mongo_db
    if _use_mongo and _mongo_db is not None:
        try:
            _mongo_db.users.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "first_name": first_name,
                        "username": username,
                        "last_active": datetime.datetime.utcnow(),
                    },
                    "$inc": {"total_requests": 1},
                },
                upsert=True
            )
        except Exception as e:
            logger.warning(f"Failed to log user to MongoDB: {e}")


def get_cached_song(query: str, quality: str = "192") -> Optional[Dict]:
    """Retrieves cached song file_id and channel info from MongoDB or SQLite."""
    global _use_mongo, _mongo_db
    norm = normalize_key(query)
    full_key = f"{norm}_{quality}"

    if _use_mongo and _mongo_db is not None:
        try:
            doc = _mongo_db.cached_songs.find_one({"query_key": full_key})
            if doc:
                _mongo_db.cached_songs.update_one(
                    {"query_key": full_key},
                    {"$inc": {"downloads": 1}}
                )
                return {
                    "file_id": doc.get("file_id"),
                    "channel_message_id": doc.get("channel_message_id"),
                    "channel_id": doc.get("channel_id"),
                    "title": doc.get("title"),
                    "artist": doc.get("artist"),
                    "duration": doc.get("duration", 0),
                    "quality": doc.get("quality", quality),
                }
        except Exception as e:
            logger.warning(f"MongoDB read error: {e}")

    # SQLite fallback
    try:
        import sqlite3
        conn = sqlite3.connect("music_bot.db")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT file_id, channel_message_id, channel_id, title, artist, duration, quality FROM cached_songs WHERE query_key = ?",
            (full_key,)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "file_id": row[0],
                "channel_message_id": row[1],
                "channel_id": row[2],
                "title": row[3],
                "artist": row[4],
                "duration": row[5],
                "quality": row[6],
            }
    except Exception as e:
        logger.warning(f"SQLite read error: {e}")

    return None


def save_cached_song(
    query: str,
    file_id: str,
    title: str,
    artist: str,
    duration: int = 0,
    quality: str = "192",
    channel_message_id: Optional[int] = None,
    channel_id: Optional[str] = None,
):
    """Saves a downloaded song's Telegram file_id & channel copy into MongoDB or SQLite."""
    global _use_mongo, _mongo_db
    norm = normalize_key(query)
    full_key = f"{norm}_{quality}"

    if _use_mongo and _mongo_db is not None:
        try:
            update_fields = {
                "file_id": file_id,
                "title": title,
                "artist": artist,
                "duration": duration,
                "quality": quality,
                "updated_at": datetime.datetime.utcnow(),
            }
            if channel_message_id:
                update_fields["channel_message_id"] = channel_message_id
            if channel_id:
                update_fields["channel_id"] = channel_id

            _mongo_db.cached_songs.update_one(
                {"query_key": full_key},
                {
                    "$set": update_fields,
                    "$setOnInsert": {
                        "downloads": 1,
                        "created_at": datetime.datetime.utcnow(),
                    }
                },
                upsert=True
            )
            logger.info(f"MongoDB cached song saved: {title} - {artist} (channel_msg: {channel_message_id})")
            return
        except Exception as e:
            logger.error(f"MongoDB write error: {e}")

    # SQLite fallback
    try:
        import sqlite3
        conn = sqlite3.connect("music_bot.db")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO cached_songs (query_key, file_id, channel_message_id, channel_id, title, artist, duration, quality)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (full_key, file_id, channel_message_id, channel_id, title, artist, duration, quality)
        )
        conn.commit()
        conn.close()
        logger.info(f"SQLite cached song saved: {title} by {artist}")
    except Exception as e:
        logger.error(f"SQLite write error: {e}")
