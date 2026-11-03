"""
Automatic Spotify Playlist Creator & Batch Track Pusher.
Authenticates with your Spotify account, creates a new playlist,
and automatically pushes thousands of filtered tracks in batches of 100 in seconds.
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
from spotify_helper import fetch_universal_metadata

DEFAULT_PLAYLIST_NAME = "Tamil All-Time Master Hits (1980 - 2026)"
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
    parser = argparse.ArgumentParser(description="Create a Spotify playlist and auto-add thousands of tracks.")
    parser.add_argument("--name", default=DEFAULT_PLAYLIST_NAME, help="Name of the new Spotify playlist")
    parser.add_argument("--url", required=True, help="Source Spotify playlist URL to pull songs from")
    parser.add_argument("--filter-existing", action="store_true", help="Only add songs that are NOT already in your 3643 local library")
    parser.add_argument("--limit", type=int, default=10000, help="Maximum tracks to process")
    parser.add_argument("--private", action="store_true", help="Make playlist private (default: public)")
    args = parser.parse_args()

    print("=" * 65)
    print("🚀 AUTOMATIC SPOTIFY PLAYLIST CREATOR")
    print(f"🎵 New Playlist Name: {args.name}")
    print(f"🔗 Source URL:        {args.url}")
    print("=" * 65)

    existing_set = set()
    if args.filter_existing:
        print(f"📁 Scanning master library: {DEFAULT_FOLDER}")
        existing_set = get_existing_song_names(DEFAULT_FOLDER)
        print(f"✓ Found {len(existing_set)} songs to filter against.")

    print(f"\n[1/3] Fetching tracks from source playlist...")
    meta = fetch_universal_metadata(args.url, max_tracks=args.limit)
    tracks = meta.get("tracks", []) if meta else []
    print(f"✓ Loaded {len(tracks)} tracks from source.")

    # Deduplicate and extract valid URIs
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
    print(f"\n[2/3] Filter & Preparation Results:")
    print(f"   ✓ Filtered out duplicates / existing: {len(tracks) - total_to_add}")
    print(f"   ✨ Unique Tracks to add to Spotify:   {total_to_add}")

    if total_to_add == 0:
        print("[!] No tracks to add. Everything already filtered out.")
        return

    print(f"\n[3/3] Authenticating with your Spotify account...")
    sp = get_spotify_client()
    user_info = sp.current_user()
    user_id = user_info["id"]
    display_name = user_info.get("display_name", user_id)
    print(f"✓ Connected as: {display_name} (ID: {user_id})")

    # Create Playlist
    is_public = not args.private
    desc = f"Curated Master Collection with {total_to_add} unique songs (Automated via CinePrime Music)."
    print(f"\nCreating playlist: '{args.name}'...")
    new_pl = sp.user_playlist_create(
        user=user_id,
        name=args.name,
        public=is_public,
        description=desc
    )
    new_pl_id = new_pl["id"]
    new_pl_url = new_pl.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{new_pl_id}")
    print(f"✓ Playlist created successfully! ID: {new_pl_id}")

    # Push in batches of 100
    batch_size = 100
    added = 0
    print(f"\nAdding {total_to_add} tracks in batches of 100...")

    for i in range(0, total_to_add, batch_size):
        batch = track_uris[i:i + batch_size]
        try:
            sp.playlist_add_items(new_pl_id, batch)
            added += len(batch)
            print(f"[{added}/{total_to_add}] ✓ Added {len(batch)} songs...")
            time.sleep(0.2)
        except Exception as e:
            print(f"[!] Error adding batch {i}-{i+len(batch)}: {e}")
            time.sleep(1.0)

    print("\n" + "=" * 65)
    print("🎉 PLAYLIST CREATION COMPLETE!")
    print(f"   ✓ Total Songs Added: {added}")
    print(f"🔗 Open Your New Playlist Here:")
    print(f"   👉 {new_pl_url}")
    print("=" * 65)

if __name__ == "__main__":
    main()
