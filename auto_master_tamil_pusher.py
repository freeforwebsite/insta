"""
Autonomous Tamil Mega-Playlist Aggregator & Continuous Stream Pusher.
Scans multiple top Tamil playlists, filters out all existing tracks in your Spotify playlist,
and continuously auto-pushes all new songs in batches of 100 into your playlist!
"""

import os
import sys
import argparse
import time
import re
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
from redownload_missing import normalize_title
from spotify_helper import fetch_universal_metadata, parse_spotify_url

# Default Target: Your Master Playlist
DEFAULT_TARGET_PLAYLIST = "39Pn6viey8ByVsMOD8jnuZ"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

# Top Curated Tamil Mega Playlists across all eras (1950 - 2026)
CURATED_TAMIL_PLAYLISTS = [
    {
        "name": "Tamil All Time Hits (1980-2026 Master - 4,595 Songs)",
        "url": "https://open.spotify.com/playlist/7eMHkKCKwelg7afYViQMAf"
    },
    {
        "name": "Top Hit Tamil Songs (2000-2025 Ponraj - 8,333 Songs)",
        "url": "https://open.spotify.com/playlist/3Iwa9T27AqqcBd9j1xHsVW"
    },
    {
        "name": "Latest Tamil Songs Mega Library (5,296 Songs)",
        "url": "https://open.spotify.com/playlist/7CcS1hPHyor4X6CXzNpPRy"
    },
    {
        "name": "Tamil Songs Master Collection 130+ Hours (1,500+ Songs)",
        "url": "https://open.spotify.com/playlist/732kV3P6L4bFhJ7K3X1r2V"
    },
    {
        "name": "Top Hit Tamil Songs 2000-2026 (570+ Songs)",
        "url": "https://open.spotify.com/playlist/27l87fJ58Z3c7U23K8l7fJ"
    },
    {
        "name": "Ilaiyaraaja Golden Melodies Master",
        "url": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    },
    {
        "name": "Tamil 2000s Evergreen Melodies",
        "url": "https://open.spotify.com/playlist/37i9dQZF1DX4XtozpdvZpb"
    },
    {
        "name": "Tamil 2024-2026 New Releases",
        "url": "https://open.spotify.com/playlist/04wyLWYsskgWjn9827AQj3"
    }
]

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

def fetch_existing_target_items(sp, target_id):
    """Fetches all track URIs and normalized titles currently inside your target Spotify playlist."""
    print("⏳ Scanning your target Spotify playlist to detect all current songs...")
    existing_uris = set()
    existing_normalized = set()
    offset = 0

    while True:
        try:
            results = sp.playlist_items(
                target_id,
                fields="items.track.uri,items.track.name,next,total",
                limit=100,
                offset=offset
            )
        except Exception as e:
            print(f"[!] Warning while reading target playlist at offset {offset}: {e}")
            break

        items = results.get("items", [])
        if not items:
            break

        for item in items:
            trk = item.get("track")
            if not trk:
                continue
            uri = trk.get("uri")
            name = trk.get("name")
            if uri:
                existing_uris.add(uri)
            if name:
                norm = normalize_title(name)
                if norm:
                    existing_normalized.add(norm)

        offset += len(items)
        if not results.get("next"):
            break

    print(f"✓ Found {len(existing_uris)} total tracks ({len(existing_normalized)} unique titles) in your playlist.")
    return existing_uris, existing_normalized

def main():
    parser = argparse.ArgumentParser(description="Autonomous Tamil Multi-Playlist Continuous Filter & Pusher.")
    parser.add_argument("--target", default=None, help="Target Spotify playlist ID (leave empty with --create-new to auto-create Vol 2)")
    parser.add_argument("--create-new", action="store_true", help="Automatically create a new Volume playlist (e.g. Vol 2)")
    parser.add_argument("--name", default="🎵 Tamil Songs 💖 | All Time Hits ✨ - Vol 2", help="Name for the new Volume playlist")
    parser.add_argument("--filter-from", default=DEFAULT_TARGET_PLAYLIST, help="Previous volume playlist to filter against (prevents duplicates across volumes)")
    parser.add_argument("--file", default=None, help="Optional text file with extra playlist URLs to scan (one per line)")
    args = parser.parse_args()

    # Authenticate with Spotify
    sp = get_spotify_client()
    user_info = sp.current_user()
    user_id = user_info["id"]
    display_name = user_info.get("display_name", user_id)
    print("=" * 70)
    print("👑 AUTONOMOUS TAMIL MEGA-PLAYLIST PUSHER (MULTI-VOLUME)")
    print(f"✓ Connected as: {display_name} (ID: {user_id})")

    # If --create-new or target is None, create new volume playlist
    if args.create_new or not args.target:
        print(f"\nCreating new Volume playlist: '{args.name}'...")
        desc = "The ultimate Tamil music collection 🎵 | All-In-One Master Archive (Vol 2)."
        new_pl = sp.user_playlist_create(user=user_id, name=args.name, public=True, description=desc)
        target_id = new_pl["id"]
        target_url = new_pl.get("external_urls", {}).get("spotify", f"https://open.spotify.com/playlist/{target_id}")
        print(f"✓ Created new Volume playlist: {target_url}")
    else:
        target_id = args.target
        if "open.spotify.com" in target_id:
            parsed = parse_spotify_url(target_id)
            if parsed:
                target_id = parsed[1]
        target_url = f"https://open.spotify.com/playlist/{target_id}"

    print(f"🎯 Target Playlist: {target_url}")
    print("=" * 70)

    # Gather all playlists to process
    playlists_to_process = list(CURATED_TAMIL_PLAYLISTS)
    if args.file and os.path.exists(args.file):
        with open(args.file, "r", encoding="utf-8") as f:
            for line in f:
                url = line.strip()
                if url and "open.spotify.com" in url:
                    playlists_to_process.append({"name": f"Custom Playlist ({url[:35]}...)", "url": url})

    print(f"📋 Loaded {len(playlists_to_process)} major Tamil playlists into queue for scanning.")

    # 1. Fetch live existing songs from previous volume (to prevent duplicates across Volume 1 & Volume 2)
    existing_uris = set()
    existing_normalized = set()

    if args.filter_from:
        filter_id = args.filter_from
        if "open.spotify.com" in filter_id:
            p = parse_spotify_url(filter_id)
            if p:
                filter_id = p[1]
        print(f"📁 Filtering against Volume 1 (https://open.spotify.com/playlist/{filter_id})...")
        v1_uris, v1_norm = fetch_existing_target_items(sp, filter_id)
        existing_uris |= v1_uris
        existing_normalized |= v1_norm

    # 2. If target playlist is existing, also check what's in target
    if target_id != args.filter_from:
        t_uris, t_norm = fetch_existing_target_items(sp, target_id)
        existing_uris |= t_uris
        existing_normalized |= t_norm

    total_newly_added = 0
    hit_limit = False

    for idx, pl in enumerate(playlists_to_process, 1):
        if hit_limit:
            break

        pl_name = pl["name"]
        pl_url = pl["url"]
        print("\n" + "-" * 70)
        print(f"[{idx}/{len(playlists_to_process)}] 🔍 Scanning: {pl_name}")
        print(f"    URL: {pl_url}")

        try:
            meta = fetch_universal_metadata(pl_url, max_tracks=10000)
            tracks = meta.get("tracks", []) if meta else []
        except Exception as e:
            print(f"    [!] Error fetching metadata: {e}")
            continue

        if not tracks:
            print("    [!] No tracks returned, skipping.")
            continue

        # Filter against what is ALREADY in your playlist
        new_batch_uris = []
        for t in tracks:
            norm = normalize_title(t.get("title", ""))
            uri = t.get("uri")
            if not uri and t.get("id"):
                uri = f"spotify:track:{t['id']}"

            if not uri or not norm:
                continue

            if uri in existing_uris or norm in existing_normalized:
                continue

            # It's brand new!
            new_batch_uris.append(uri)
            existing_uris.add(uri)
            existing_normalized.add(norm)

        print(f"    ✓ Loaded: {len(tracks)} tracks")
        print(f"    ✨ Brand-New Unique Tracks to Add: {len(new_batch_uris)}")

        if not new_batch_uris:
            print("    ✓ All songs from this playlist already in your collection. Skipping to next.")
            continue

        # Push into Spotify playlist in batches of 100
        batch_size = 100
        pl_added = 0
        for b_start in range(0, len(new_batch_uris), batch_size):
            chunk = new_batch_uris[b_start:b_start + batch_size]
            try:
                sp.playlist_add_items(target_id, chunk)
                pl_added += len(chunk)
                total_newly_added += len(chunk)
                print(f"    [{pl_added}/{len(new_batch_uris)}] ✓ Added {len(chunk)} songs (Total Added: {total_newly_added})...")
                time.sleep(0.3)
            except Exception as e:
                err_str = str(e)
                print(f"    [!] Spotify error on adding batch: {e}")
                if "limit reached" in err_str.lower() or "400" in err_str or "403" in err_str:
                    print("\n⚠️ Spotify playlist has reached its absolute maximum cloud limit!")
                    hit_limit = True
                    break
                time.sleep(1.0)

    print("\n" + "=" * 70)
    print("🎉 ALL PLAYLISTS PROCESSED SUCCESSFULLY!")
    print(f"   ✓ Brand-New Songs Pushed to Spotify: {total_newly_added}")
    print(f"🔗 Check your Master Playlist now:")
    print(f"   👉 https://open.spotify.com/playlist/{target_id}")
    print("=" * 70)

if __name__ == "__main__":
    main()
