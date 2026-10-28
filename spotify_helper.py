import os
import re
import json
import base64
import logging
import urllib.request
import urllib.parse
from typing import List, Dict, Optional, Tuple
import requests
import yt_dlp
import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, COMM, TPUB, TCOP, error

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


def get_spotify_api_token(client_id: str, client_secret: str) -> Optional[str]:
    """Generates an app access token from Spotify Web API."""
    try:
        auth_url = "https://accounts.spotify.com/api/token"
        auth_header = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        resp = requests.post(
            auth_url,
            headers={"Authorization": f"Basic {auth_header}"},
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
        data = resp.json()
        return data.get("access_token")
    except Exception as e:
        logger.error(f"Error getting Spotify API token: {e}")
        return None


def fetch_spotify_via_api(item_type: str, item_id: str, client_id: str, client_secret: str) -> Optional[Dict]:
    """
    Fetches ALL tracks from Spotify with full pagination (supports 100, 152, 500+ tracks).
    """
    token = get_spotify_api_token(client_id, client_secret)
    if not token:
        return None

    headers = {"Authorization": f"Bearer {token}"}
    try:
        if item_type == "track":
            resp = requests.get(f"https://api.spotify.com/v1/tracks/{item_id}", headers=headers, timeout=10)
            data = resp.json()
            title = data.get("name", "Unknown Track")
            artists = ", ".join(a.get("name", "") for a in data.get("artists", []))
            duration = (data.get("duration_ms") or 0) // 1000
            thumb = data.get("album", {}).get("images", [{}])[0].get("url")
            return {
                "platform": "spotify",
                "type": "track",
                "id": item_id,
                "title": title,
                "thumbnail_url": thumb,
                "tracks": [{
                    "title": title,
                    "artist": artists,
                    "duration": duration,
                    "thumbnail_url": thumb,
                }],
            }

        elif item_type == "playlist":
            resp = requests.get(f"https://api.spotify.com/v1/playlists/{item_id}", headers=headers, timeout=10)
            p_data = resp.json()
            title = p_data.get("name", "Spotify Playlist")
            thumb = p_data.get("images", [{}])[0].get("url") if p_data.get("images") else None

            # Paginate through ALL tracks
            tracks = []
            next_url = f"https://api.spotify.com/v1/playlists/{item_id}/tracks?limit=100"
            while next_url:
                t_resp = requests.get(next_url, headers=headers, timeout=15)
                t_data = t_resp.json()
                for item in t_data.get("items", []):
                    track = item.get("track")
                    if not track:
                        continue
                    t_title = track.get("name", "Unknown Title")
                    t_artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                    t_dur = (track.get("duration_ms") or 0) // 1000
                    t_thumb = track.get("album", {}).get("images", [{}])[0].get("url") if track.get("album", {}).get("images") else thumb
                    tracks.append({
                        "title": t_title,
                        "artist": t_artists,
                        "duration": t_dur,
                        "thumbnail_url": t_thumb,
                    })
                next_url = t_data.get("next")

            return {
                "platform": "spotify",
                "type": "playlist",
                "id": item_id,
                "title": title,
                "thumbnail_url": thumb,
                "tracks": tracks,
            }

        elif item_type == "album":
            resp = requests.get(f"https://api.spotify.com/v1/albums/{item_id}", headers=headers, timeout=10)
            a_data = resp.json()
            title = a_data.get("name", "Spotify Album")
            thumb = a_data.get("images", [{}])[0].get("url") if a_data.get("images") else None

            tracks = []
            next_url = f"https://api.spotify.com/v1/albums/{item_id}/tracks?limit=50"
            while next_url:
                t_resp = requests.get(next_url, headers=headers, timeout=15)
                t_data = t_resp.json()
                for track in t_data.get("items", []):
                    t_title = track.get("name", "Unknown Title")
                    t_artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                    t_dur = (track.get("duration_ms") or 0) // 1000
                    tracks.append({
                        "title": t_title,
                        "artist": t_artists,
                        "duration": t_dur,
                        "thumbnail_url": thumb,
                    })
                next_url = t_data.get("next")

            return {
                "platform": "spotify",
                "type": "album",
                "id": item_id,
                "title": title,
                "thumbnail_url": thumb,
                "tracks": tracks,
            }

        elif item_type == "artist":
            resp = requests.get(f"https://api.spotify.com/v1/artists/{item_id}", headers=headers, timeout=10)
            art_data = resp.json()
            title = art_data.get("name", "Spotify Artist")
            thumb = art_data.get("images", [{}])[0].get("url") if art_data.get("images") else None

            # Get Top Tracks
            top_resp = requests.get(f"https://api.spotify.com/v1/artists/{item_id}/top-tracks?market=IN", headers=headers, timeout=10)
            top_data = top_resp.json()
            tracks = []
            for track in top_data.get("tracks", []):
                t_title = track.get("name", "Unknown Title")
                t_artists = ", ".join(a.get("name", "") for a in track.get("artists", []))
                t_dur = (track.get("duration_ms") or 0) // 1000
                t_thumb = track.get("album", {}).get("images", [{}])[0].get("url") if track.get("album", {}).get("images") else thumb
                tracks.append({
                    "title": t_title,
                    "artist": t_artists,
                    "duration": t_dur,
                    "thumbnail_url": t_thumb,
                })

            return {
                "platform": "spotify",
                "type": "artist",
                "id": item_id,
                "title": title,
                "thumbnail_url": thumb,
                "tracks": tracks,
            }

    except Exception as e:
        logger.error(f"Error in Spotify API fetch: {e}")

    return None


def fetch_spotify_via_spotapi(item_id: str) -> Optional[Dict]:
    """
    Fetches ALL tracks from a Spotify playlist (100, 152, 500+ tracks)
    using Spotify's public pathfinder GraphQL API via spotapi (no premium needed).
    """
    try:
        import spotapi
        p = spotapi.PublicPlaylist(item_id)
        info = p.get_playlist_info(limit=5)
        data = info.get("data", {}).get("playlistV2", {})
        title = data.get("name", "Spotify Playlist")
        images = data.get("images", {}).get("items", [])
        thumb = images[0].get("sources", [{}])[0].get("url") if images else None

        tracks = []
        for chunk in p.paginate_playlist():
            for item in chunk.get("items", []):
                track_data = item.get("itemV2", {}).get("data", {})
                t_name = track_data.get("name")
                if not t_name:
                    continue
                artists_items = track_data.get("artists", {}).get("items", [])
                t_artists = ", ".join(a.get("profile", {}).get("name", "") for a in artists_items)
                t_dur = (track_data.get("trackDuration", {}).get("totalMilliseconds") or 0) // 1000
                tracks.append({
                    "title": t_name,
                    "artist": t_artists,
                    "duration": t_dur,
                    "thumbnail_url": thumb,
                })

        if tracks:
            logger.info(f"spotapi successfully fetched {len(tracks)} tracks for playlist {item_id}")
            return {
                "platform": "spotify",
                "type": "playlist",
                "id": item_id,
                "title": title,
                "thumbnail_url": thumb,
                "tracks": tracks,
            }
    except Exception as e:
        logger.warning(f"spotapi playlist fetch failed: {e}")

    return None


def fetch_universal_metadata(url: str) -> Optional[Dict]:
    """
    Extracts metadata from Spotify, YouTube, JioSaavn, Apple Music, Wynk, or SoundCloud.
    """
    platform = detect_platform(url)

    if platform == "spotify":
        parsed = parse_spotify_url(url)
        # 1. Try spotapi pathfinder API (supports 100, 152, 500+ tracks without Spotify Premium)
        if parsed and parsed[0] == "playlist":
            spotapi_meta = fetch_spotify_via_spotapi(parsed[1])
            if spotapi_meta and spotapi_meta.get("tracks"):
                return spotapi_meta

        # 2. Check if official Spotify API credentials exist in environment
        client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip() or os.getenv("SPOTIPY_CLIENT_ID", "").strip()
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or os.getenv("SPOTIPY_CLIENT_SECRET", "").strip()

        if client_id and client_secret and parsed:
            api_meta = fetch_spotify_via_api(parsed[0], parsed[1], client_id, client_secret)
            if api_meta and api_meta.get("tracks"):
                return api_meta

        # 3. Fallback to Embed Scraper (first 100 tracks)
        meta = fetch_spotify_embed_metadata(url)
        if meta:
            meta["platform"] = "spotify"
        return meta

    if platform in ["youtube", "jiosaavn", "soundcloud"]:
        return fetch_ytdlp_metadata(url, platform)

    if platform == "applemusic":
        return fetch_applemusic_metadata(url)

    if platform == "wynk":
        return fetch_wynk_metadata(url)

    return fetch_ytdlp_metadata(url, "generic")


def fetch_spotify_embed_metadata(url: str) -> Optional[Dict]:
    """Extracts metadata from Spotify embed (capped at first 100 tracks by Spotify)."""
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
        logger.error(f"Error fetching Spotify embed metadata: {e}")
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


def embed_metadata(
    mp3_path: str,
    title: str,
    artist: str,
    thumbnail_url: Optional[str] = None,
    album: Optional[str] = None,
):
    """Embeds ID3 metadata, CinePrime branding, and cover art directly into the MP3 file."""
    try:
        audio = MP3(mp3_path, ID3=ID3)
        try:
            audio.add_tags()
        except error:
            pass

        audio.tags.add(TIT2(encoding=3, text=title))
        audio.tags.add(TPE1(encoding=3, text=artist))

        # CinePrime Branding Tags
        album_name = f"{album} - CinePrime" if album else "CinePrime Music"
        audio.tags.add(TALB(encoding=3, text=album_name))
        audio.tags.add(TPUB(encoding=3, text="CinePrime Music"))
        audio.tags.add(TCOP(encoding=3, text="CinePrime Hub (@cineprimehub)"))
        audio.tags.add(
            COMM(
                encoding=3,
                lang="eng",
                desc="Channel",
                text="Downloaded via @CinePrimeMusicBot | Join @cineprimehub",
            )
        )

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


def download_from_saavn_cdn(
    query: str,
    output_dir: str,
    filename_prefix: str = "",
    quality: str = "320",
    title: Optional[str] = None,
    artist: Optional[str] = None,
    thumbnail_url: Optional[str] = None,
    album: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Directly searches and downloads high-quality audio from JioSaavn CDN.
    Completely bypasses YouTube bot verification on cloud servers (AWS EC2).
    """
    try:
        from Crypto.Cipher import DES
        import subprocess

        clean_query = query.replace("audio", "").strip()
        search_url = f"https://www.jiosaavn.com/api.php?__call=search.getResults&_format=json&n=3&p=1&q={urllib.parse.quote(clean_query)}"
        r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if not r.ok:
            return None
        data = r.json()
        results = data.get("results", [])
        if not results:
            return None

        s = results[0]
        enc_url = s.get("encrypted_media_url")
        if not enc_url:
            return None

        cipher = DES.new(b"38346591", DES.MODE_ECB)
        dec = cipher.decrypt(base64.b64decode(enc_url))
        pad = dec[-1]
        raw_cdn = dec[:-pad].decode("utf-8")

        bitrate_suffix = "_320.mp4" if str(quality) in ["320", "256"] else "_160.mp4"
        cdn_url = raw_cdn.replace("_96.mp4", bitrate_suffix)

        os.makedirs(output_dir, exist_ok=True)
        safe_name = re.sub(r'[\\/*?:"<>|]', "", title or clean_query)[:50].strip()
        temp_mp4 = os.path.join(output_dir, f"{filename_prefix}{safe_name}_saavn.mp4")
        final_mp3 = os.path.join(output_dir, f"{filename_prefix}{safe_name}.mp3")

        with requests.get(cdn_url, stream=True, timeout=15) as resp:
            if resp.status_code != 200:
                cdn_url = raw_cdn.replace("_96.mp4", "_160.mp4")
                resp = requests.get(cdn_url, stream=True, timeout=15)
            if resp.status_code != 200:
                return None

            tot_bytes = int(resp.headers.get("content-length", 0))
            dl_bytes = 0
            with open(temp_mp4, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        dl_bytes += len(chunk)
                        if progress_callback and tot_bytes:
                            progress_callback({
                                "status": "downloading",
                                "downloaded_bytes": dl_bytes,
                                "total_bytes": tot_bytes,
                                "speed": 4 * 1024 * 1024,
                                "eta": int((tot_bytes - dl_bytes) / (4 * 1024 * 1024)),
                            })

        if progress_callback:
            progress_callback({"status": "finished", "total_bytes": tot_bytes})

        ffmpeg_cmd = [
            "ffmpeg", "-y", "-i", temp_mp4,
            "-b:a", f"{quality}k",
            final_mp3
        ]
        res = subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(temp_mp4):
            try:
                os.remove(temp_mp4)
            except Exception:
                pass

        if res.returncode == 0 and os.path.exists(final_mp3):
            t_name = title or s.get("title") or clean_query
            a_name = artist or s.get("singers") or "CinePrime Music"
            t_thumb = thumbnail_url or s.get("image", "").replace("150x150", "500x500")
            alb_name = album or s.get("more_info", {}).get("album") or "CinePrime Music"
            embed_metadata(final_mp3, t_name, a_name, t_thumb, album=alb_name)
            logger.info(f"Successfully downloaded from JioSaavn CDN with CinePrime branding: {t_name}")
            return final_mp3

    except Exception as e:
        logger.warning(f"JioSaavn CDN download failed for {query}: {e}")

    return None


def download_song(
    query: str,
    output_dir: str,
    filename_prefix: str = "",
    language: Optional[str] = None,
    quality: str = "192",
    thumbnail_url: Optional[str] = None,
    title: Optional[str] = None,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    progress_callback: Optional[callable] = None,
) -> Optional[str]:
    """
    Downloads audio matching query using yt-dlp and ffmpeg, converting to MP3.
    Applies audio quality bitrate and embeds ID3 tags, CinePrime branding, and album cover art.
    Supports dynamic progress updates via progress_callback.
    """
    # 1. Primary engine: JioSaavn CDN direct download (bypasses YouTube datacenter blocks)
    if not (query.startswith("http://") or query.startswith("https://")):
        saavn_mp3 = download_from_saavn_cdn(
            query=query,
            output_dir=output_dir,
            filename_prefix=filename_prefix,
            quality=quality,
            title=title,
            artist=artist,
            thumbnail_url=thumbnail_url,
            album=album,
            progress_callback=progress_callback,
        )
        if saavn_mp3 and os.path.exists(saavn_mp3):
            return saavn_mp3

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
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios"]
            }
        },
    }

    # Automatically load YouTube cookies if present in project directory
    cookie_file = os.getenv("YOUTUBE_COOKIE_FILE", "cookies.txt")
    if os.path.exists(cookie_file) and os.path.getsize(cookie_file) > 10:
        ydl_opts["cookiefile"] = cookie_file
        logger.info(f"Loaded YouTube authentication cookies from: {cookie_file}")

    if progress_callback:
        def hook(d):
            try:
                progress_callback(d)
            except Exception:
                pass
        ydl_opts["progress_hooks"] = [hook]

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
                for extra in os.listdir(output_dir):
                    if extra.startswith(filename_prefix) and not extra.lower().endswith(".mp3"):
                        try:
                            os.remove(os.path.join(output_dir, extra))
                        except Exception:
                            pass

                t_name = title or query
                a_name = artist or "CinePrime Music"
                embed_metadata(downloaded_mp3, t_name, a_name, thumbnail_url, album=album)

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
