import os
import re
import json
import logging
import urllib.request
from typing import List, Dict, Optional, Tuple
import requests
import yt_dlp
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, error

logger = logging.getLogger(__name__)

SPOTIFY_URL_REGEX = re.compile(
    r"https?://open\.spotify\.com/(?P<type>track|playlist|album|artist)/(?P<id>[a-zA-Z0-9]+)"
)

YOUTUBE_URL_REGEX = re.compile(
    r"(https?://)?(www\.)?(youtube\.com/|youtu\.be/|music\.youtube\.com/)"
)

JIOSAAVN_URL_REGEX = re.compile(
    r"https?://(www\.)?(jiosaavn\.com|saavn\.com)/(song|album|featured|artist)/"
)

APPLE_MUSIC_URL_REGEX = re.compile(
    r"https?://music\.apple\.com/(?P<country>[a-zA-Z]{2})/(?P<type>album|song|playlist|artist)/"
)

WYNK_URL_REGEX = re.compile(
    r"https?://wynk\.in/music/(?P<type>song|album|playlist|package)/"
)

SOUNDCLOUD_URL_REGEX = re.compile(
    r"https?://(www\.)?soundcloud\.com/"
)


def detect_platform(url: str) -> str:
    """Identifies the music platform from URL."""
    if SPOTIFY_URL_REGEX.search(url):
        return "spotify"
    if YOUTUBE_URL_REGEX.search(url):
        return "youtube"
    if JIOSAAVN_URL_REGEX.search(url):
        return "jiosaavn"
    if APPLE_MUSIC_URL_REGEX.search(url):
        return "applemusic"
    if WYNK_URL_REGEX.search(url):
        return "wynk"
    if SOUNDCLOUD_URL_REGEX.search(url):
        return "soundcloud"
    return "unknown"


def parse_spotify_url(url: str) -> Optional[Tuple[str, str]]:
    """Extracts type ('track', 'playlist', 'album', 'artist') and ID from Spotify URL."""
    match = SPOTIFY_URL_REGEX.search(url)
    if match:
        return match.group("type"), match.group("id")
    return None


def fetch_universal_metadata(url: str) -> Optional[Dict]:
    """
    Extracts metadata from Spotify, YouTube, JioSaavn, Apple Music, Wynk, or SoundCloud.
    Returns:
    {
        'platform': str,
        'type': 'track' | 'playlist' | 'album' | 'artist',
        'title': str,
        'thumbnail_url': str,
        'tracks': List[Dict]
    }
    """
    platform = detect_platform(url)

    if platform == "spotify":
        meta = fetch_spotify_metadata(url)
        if meta:
            meta["platform"] = "spotify"
        return meta

    if platform in ["youtube", "jiosaavn", "soundcloud"]:
        return fetch_ytdlp_metadata(url, platform)

    if platform == "applemusic":
        return fetch_applemusic_metadata(url)

    if platform == "wynk":
        return fetch_wynk_metadata(url)

    # Fallback to general yt-dlp extraction
    return fetch_ytdlp_metadata(url, "generic")


def fetch_spotify_metadata(url: str) -> Optional[Dict]:
    """Extracts metadata from Spotify embed."""
    parsed = parse_spotify_url(url)
    if not parsed:
        return None

    item_type, item_id = parsed
    clean_embed_url = f"https://open.spotify.com/embed/{item_type}/{item_id}"

    try:
        req = urllib.request.Request(
            clean_embed_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode("utf-8")

        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not m:
            return None

        data = json.loads(m.group(1))
        entity = (
            data.get("props", {})
            .get("pageProps", {})
            .get("state", {})
            .get("data", {})
            .get("entity", {})
        )

        title = entity.get("name") or entity.get("title") or "Unknown Spotify Item"
        thumbnail_url = None
        cover_art = entity.get("coverArt", {}).get("sources", [])
        if cover_art:
            thumbnail_url = cover_art[0].get("url")
        elif entity.get("visualIdentity", {}).get("image", []):
            thumbnail_url = entity.get("visualIdentity", {}).get("image", [])[0].get("url")

        tracks = []
        if item_type == "track":
            artists_data = entity.get("artists") or entity.get("subtitle") or "Unknown Artist"
            if isinstance(artists_data, list):
                artist_name = ", ".join(a.get("name", "") for a in artists_data if isinstance(a, dict))
            else:
                artist_name = str(artists_data)

            duration_ms = entity.get("duration", 0)
            tracks.append({
                "title": title,
                "artist": artist_name,
                "duration": duration_ms // 1000 if duration_ms else 0,
                "thumbnail_url": thumbnail_url,
            })
        else:
            raw_track_list = entity.get("trackList", [])
            for item in raw_track_list:
                t_title = item.get("title", "Unknown Title")
                t_artist = item.get("subtitle") or (title if item_type == "artist" else "Unknown Artist")
                t_duration = item.get("duration", 0)
                tracks.append({
                    "title": t_title,
                    "artist": t_artist,
                    "duration": t_duration // 1000 if t_duration else 0,
                    "thumbnail_url": thumbnail_url,
                })

        return {
            "platform": "spotify",
            "type": item_type,
            "id": item_id,
            "title": title,
            "thumbnail_url": thumbnail_url,
            "tracks": tracks,
        }
    except Exception as e:
        logger.error(f"Error fetching Spotify metadata: {e}")
        return None


def fetch_ytdlp_metadata(url: str, platform_name: str) -> Optional[Dict]:
    """Extracts metadata for YouTube, JioSaavn, or SoundCloud via yt-dlp."""
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                return None

            is_playlist = "entries" in info and bool(info["entries"])
            title = info.get("title") or "Music Collection"
            thumbnail_url = info.get("thumbnail")

            tracks = []
            if is_playlist:
                for entry in info["entries"]:
                    if not entry:
                        continue
                    tracks.append({
                        "title": entry.get("title", "Unknown Title"),
                        "artist": entry.get("uploader") or entry.get("artist") or title,
                        "duration": int(entry.get("duration") or 0),
                        "thumbnail_url": entry.get("thumbnail") or thumbnail_url,
                        "url": entry.get("url") or entry.get("webpage_url") or url,
                    })
                item_type = "playlist"
            else:
                artist_name = info.get("artist") or info.get("uploader") or info.get("creator") or "Unknown Artist"
                tracks.append({
                    "title": title,
                    "artist": artist_name,
                    "duration": int(info.get("duration") or 0),
                    "thumbnail_url": thumbnail_url,
                    "url": url,
                })
                item_type = "track"

            return {
                "platform": platform_name,
                "type": item_type,
                "id": info.get("id", "track"),
                "title": title,
                "thumbnail_url": thumbnail_url,
                "tracks": tracks,
            }
    except Exception as e:
        logger.error(f"Error in yt-dlp metadata for {url}: {e}")
        return None


def fetch_applemusic_metadata(url: str) -> Optional[Dict]:
    """Extracts metadata from Apple Music link."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")

        m_title = re.search(r'<meta property="og:title" content="([^"]+)"', html)
        m_image = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        raw_title = m_title.group(1) if m_title else "Apple Music Track"
        thumb_url = m_image.group(1) if m_image else None

        # Clean "Song Name by Artist on Apple Music"
        clean_title = re.sub(r"\s+on Apple\s*Music.*", "", raw_title).strip()
        parts = clean_title.split(" by ")
        if len(parts) == 2:
            song_name, artist_name = parts[0].strip(), parts[1].strip()
        else:
            song_name, artist_name = clean_title, "Apple Music"

        is_playlist = "playlist" in url or "album" in url
        return {
            "platform": "applemusic",
            "type": "playlist" if is_playlist else "track",
            "id": "applemusic",
            "title": clean_title,
            "thumbnail_url": thumb_url,
            "tracks": [{
                "title": song_name,
                "artist": artist_name,
                "duration": 0,
                "thumbnail_url": thumb_url,
            }],
        }
    except Exception as e:
        logger.error(f"Error fetching Apple Music metadata: {e}")
        return None


def fetch_wynk_metadata(url: str) -> Optional[Dict]:
    """Extracts metadata from Wynk Music link."""
    try:
        # Extract title slug from URL: /song/never-gonna-give-you-up/id
        m = re.search(r"wynk\.in/music/(?:song|album|playlist)/([a-zA-Z0-9-]+)", url)
        slug = m.group(1).replace("-", " ").title() if m else "Wynk Music Track"

        is_playlist = "playlist" in url or "album" in url
        return {
            "platform": "wynk",
            "type": "playlist" if is_playlist else "track",
            "id": "wynk",
            "title": slug,
            "thumbnail_url": None,
            "tracks": [{
                "title": slug,
                "artist": "Wynk Music",
                "duration": 0,
                "thumbnail_url": None,
            }],
        }
    except Exception as e:
        logger.error(f"Error fetching Wynk metadata: {e}")
        return None


def fetch_more_artist_songs(artist_name: str, language: Optional[str] = None, count: int = 30) -> List[Dict]:
    """Fetches additional songs for an artist with optional language filter."""
    lang_keyword = f" {language}" if language and language.lower() != "all" else ""
    query = f"ytsearch{count}:{artist_name}{lang_keyword} songs audio"

    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "no_warnings": True,
    }

    songs = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            res = ydl.extract_info(query, download=False)
            entries = res.get("entries", []) if res else []
            for e in entries:
                if not e:
                    continue
                song_title = e.get("title", "")
                songs.append({
                    "title": song_title,
                    "artist": artist_name,
                    "duration": int(e.get("duration") or 0),
                    "thumbnail_url": None,
                })
    except Exception as e:
        logger.error(f"Error searching extra artist songs: {e}")

    return songs


def embed_metadata(mp3_path: str, title: str, artist: str, thumbnail_url: Optional[str] = None):
    """Embeds ID3 metadata and cover art directly into the MP3 file."""
    try:
        audio = MP3(mp3_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass

        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=artist))

        # Download and embed cover image
        if thumbnail_url:
            try:
                req = urllib.request.Request(thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
                img_data = urllib.request.urlopen(req, timeout=5).read()
                audio.tags.add(
                    APIC(
                        encoding=3,
                        mime="image/jpeg",
                        type=3,
                        desc="Cover",
                        data=img_data,
                    )
                )
            except Exception as e:
                logger.warning(f"Could not download thumbnail for embedding: {e}")

        audio.save()
    except Exception as e:
        logger.warning(f"Failed to embed metadata with mutagen: {e}")


def download_song(
    query: str,
    output_dir: str,
    filename_prefix: str = "",
    language: Optional[str] = None,
    quality: str = "192",
    thumbnail_url: Optional[str] = None,
    title: Optional[str] = None,
    artist: Optional[str] = None,
) -> Optional[str]:
    """
    Downloads audio matching query using yt-dlp and ffmpeg, converting to MP3.
    Applies audio quality bitrate and embeds ID3 tags and album cover art.
    """
    os.makedirs(output_dir, exist_ok=True)
    out_template = os.path.join(output_dir, f"{filename_prefix}%(title)s.%(ext)s")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(quality),
            }
        ],
        "writethumbnail": True,
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch1",
        "noplaylist": True,
        "socket_timeout": 30,
        "retries": 3,
    }

    # If it is a direct URL, use it; otherwise search YouTube Music
    if query.startswith("http://") or query.startswith("https://"):
        search_target = query
    else:
        lang_tag = f" {language}" if language and language.lower() != "all" else ""
        search_target = f"ytsearch1:{query}{lang_tag} audio"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_target, download=True)
            if not info:
                return None

            downloaded_mp3 = None
            for f in os.listdir(output_dir):
                if f.startswith(filename_prefix) and f.lower().endswith(".mp3"):
                    downloaded_mp3 = os.path.join(output_dir, f)
                    break

            if downloaded_mp3 and os.path.exists(downloaded_mp3):
                # Clean up any leftover thumbnail files
                for extra in os.listdir(output_dir):
                    if extra.startswith(filename_prefix) and not extra.lower().endswith(".mp3"):
                        try:
                            os.remove(os.path.join(output_dir, extra))
                        except Exception:
                            pass

                # Embed cover art and tags
                t_name = title or query
                a_name = artist or "CinePrime Music"
                embed_metadata(downloaded_mp3, t_name, a_name, thumbnail_url)

                return downloaded_mp3

            return None
    except Exception as e:
        logger.error(f"Error downloading song for query '{query}': {e}")
        return None


def upload_to_catbox(file_path: str) -> Optional[str]:
    """Uploads file to Catbox.moe as high-speed failover backup."""
    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                "https://catbox.moe/user/api.php",
                data={"reqtype": "fileupload"},
                files={"fileToUpload": (os.path.basename(file_path), f)},
                timeout=180,
            )
        if resp.status_code == 200 and resp.text.startswith("http"):
            return resp.text.strip()
    except Exception as e:
        logger.error(f"Catbox upload error: {e}")
    return None


def upload_cloud_file(file_path: str, gofile_token: Optional[str] = None) -> Dict:
    """
    Uploads a file to cloud with automatic failover:
    Primary: Gofile.io (No size limit)
    Failover: Catbox.moe
    Returns dict: {'url': str, 'host': str, 'fileName': str, 'fileSize': int}
    """
    if not os.path.exists(file_path):
        return {"error": "File not found"}

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)

    # 1. Attempt Gofile (Primary)
    try:
        url = "https://upload.gofile.io/uploadfile"
        headers = {}
        if gofile_token:
            headers["Authorization"] = f"Bearer {gofile_token}"

        with open(file_path, "rb") as f:
            resp = requests.post(url, headers=headers, files={"file": (file_name, f)}, timeout=300)

        data = resp.json()
        if data.get("status") == "ok":
            dl_page = data.get("data", {}).get("downloadPage")
            if dl_page:
                return {
                    "url": dl_page,
                    "host": "Gofile Cloud",
                    "fileName": file_name,
                    "fileSize": file_size,
                }
    except Exception as e:
        logger.warning(f"Gofile upload failed, trying Catbox failover: {e}")

    # 2. Catbox Failover
    catbox_url = upload_to_catbox(file_path)
    if catbox_url:
        return {
            "url": catbox_url,
            "host": "Catbox Cloud (Failover)",
            "fileName": file_name,
            "fileSize": file_size,
        }

    return {"error": "Upload failed on all cloud hosts"}
