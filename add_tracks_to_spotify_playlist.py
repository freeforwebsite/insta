"""
Add thousands of tracks automatically to your Spotify playlist without manual work.
Pushes songs in batches of 100 via Spotify API in seconds.
"""

import os
import sys
import argparse
import time
from pathlib import Path
from dotenv import load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()

import spotipy
from spotipy.oauth2 import SpotifyOAuth
from redownload_missing import get_existing_song_names, normalize_title, DEFAULT_FOLDER
from spotify_helper import fetch_universal_metadata, parse_spotify_url

DEFAULT_TARGET_PLAYLIST = "39Pn6viey8ByVsMOD8jnuZ"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

def get_spotify_client():
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip() or os.getenv("SPOTIPY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or os.getenv("SPOTIPY_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "").strip() or DEFAULT_REDIRECT_URI

    if not client_id or not client_secret:
        print("[!] Missing SPOTIFY_CLIENT_ID or SPOTIFY_CLIENT_SECRET in .env file.")
        sys.exit(1)

    sp_oauth = SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope="playlist-modify-public playlist-modify-private",
        open_browser=True,
        cache_path=".spotify_user_cache"
    )
    return spotipy.Spotify(auth_manager=sp_oauth)

def main():
    parser = argparse.ArgumentParser(description="Auto-add thousands of tracks to your existing Spotify playlist.")
    parser.add_argument("--target", default=DEFAULT_TARGET_PLAYLIST, help="Target playlist ID or URL to add songs to")
    parser.add_argument("--source", required=True, help="Source Spotify playlist URL to pull tracks from")
    parser.add_argument("--filter-existing", action="store_true", help="Filter out songs already in your 3643 songs local library")
    parser.add_argument("--limit", type=int, default=10000, help="Max tracks to fetch from source")
    args = parser.parse_args()

    # Parse target playlist id
    target_id = args.target
    if "open.spotify.com" in target_id:
        parsed = parse_spotify_url(target_id)
        if parsed:
            target_id = parsed[1]

    print("=" * 65)
    print("🚀 AUTOMATIC SPOTIFY PLAYLIST POPULATOR")
    print(f"🎯 Target Playlist: https://open.spotify.com/playlist/{target_id}")
    print(f"🔗 Source URL:      {args.source}")
    print("=" * 65)

    existing_set = set()
    if args.filter_existing:
        print(f"📁 Scanning master library: {DEFAULT_FOLDER}")
        existing_set = get_existing_song_names(DEFAULT_FOLDER)
        print(f"✓ Found {len(existing_set)} existing songs to filter out.")

    print(f"\n[1/3] Fetching tracks from source playlist...")
    meta = fetch_universal_metadata(args.source, max_tracks=args.limit)
    tracks = meta.get("tracks", []) if meta else []
    print(f"✓ Loaded {len(tracks)} tracks from source.")

    track_uris = []
    seen = set()
    for t in tracks:
        norm = normalize_title(t.get("title", ""))
        uri = t.get("uri")
        if not uri and t.get("id"):
            uri = f"spotify:track:{t['id']}"

        if not uri or not norm:
            continue

        if args.filter_existing and norm in existing_set:
            continue

        if norm not in seen:
            seen.add(norm)
            track_uris.append(uri)

    total_to_add = len(track_uris)
    print(f"\n[2/3] Filter Results:")
    print(f"   ✓ Filtered out / duplicates: {len(tracks) - total_to_add}")
    print(f"   ✨ Brand-New Tracks to Add: {total_to_add}")

    if total_to_add == 0:
        print("[!] No new tracks to add. Everything is already in your library.")
        return

    print(f"\n[3/3] Authenticating with your Spotify account...")
    print("👉 If a browser window opens, click 'Agree' to allow the script to add songs to your playlist.")
    sp = get_spotify_client()
    user_info = sp.current_user()
    display_name = user_info.get("display_name", user_info["id"])
    print(f"✓ Successfully connected as: {display_name}!")

    # Add tracks in batches of 100
    batch_size = 100
    added = 0
    print(f"\nAdding {total_to_add} songs to your playlist in batches of 100...")

    for i in range(0, total_to_add, batch_size):
        batch = track_uris[i:i + batch_size]
        try:
            sp.playlist_add_items(target_id, batch)
            added += len(batch)
            print(f"[{added}/{total_to_add}] ✓ Added {len(batch)} songs...")
            time.sleep(0.3)
        except Exception as e:
            print(f"[!] Error adding batch {i}-{i+len(batch)}: {e}")
            time.sleep(1.0)

    print("\n" + "=" * 65)
    print("🎉 ALL SONGS ADDED AUTOMATICALLY!")
    print(f"   ✓ Total Songs Added: {added}")
    print(f"🔗 Check your playlist on Spotify now:")
    print(f"   👉 https://open.spotify.com/playlist/{target_id}")
    print("=" * 65)

if __name__ == "__main__":
    main()
