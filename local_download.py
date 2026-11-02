r"""
Local Spotify Playlist & Album Downloader for Windows PC
Downloads songs directly to your local drive (D:\SpotifyMusic\) with original 640x640 album covers & ID3 tags.
Supports pause & resume (skips already downloaded files).
"""

import os
import sys
import re
import argparse
from pathlib import Path

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from spotify_helper import fetch_universal_metadata, download_song

OUTPUT_DIR = Path("D:/SpotifyMusic")
DEFAULT_QUALITY = "320"  # 320, 192, or 128 kbps

def sanitize_name(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean or "Unknown"

def main():
    parser = argparse.ArgumentParser(description="Download Spotify playlists/songs directly to PC with full metadata & covers.")
    parser.add_argument("url", nargs="?", default="", help="Spotify playlist or track URL")
    parser.add_argument("--limit", type=int, default=0, help="Number of songs to download (e.g. 5 for testing, 0 for all)")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, choices=["128", "192", "320"], help="Audio bitrate kbps")
    args = parser.parse_args()

    url = args.url.strip()
    if not url:
        url = input("🎵 Enter Spotify Playlist or Song URL: ").strip()

    if not url:
        print("[!] No URL provided. Exiting.")
        return

    limit = args.limit
    if limit <= 0 and "--limit" not in sys.argv:
        limit_input = input("🔢 How many songs to download? (Press Enter for ALL, or type 5 for a test): ").strip()
        if limit_input.isdigit():
            limit = int(limit_input)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\n[1/3] 🔍 Fetching metadata for: {url}")
    metadata = fetch_universal_metadata(url)

    if not metadata or not metadata.get("tracks"):
        print("[!] Failed to fetch playlist tracks. Please check your link.")
        return

    all_tracks = metadata["tracks"]
    total_in_playlist = len(all_tracks)
    
    if limit > 0:
        tracks = all_tracks[:limit]
    else:
        tracks = all_tracks

    playlist_title = sanitize_name(metadata.get("title", "Spotify_Playlist"))
    target_dir = OUTPUT_DIR / playlist_title
    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[2/3] 📋 Playlist: '{metadata.get('title')}'")
    print(f"      Total Songs in Playlist : {total_in_playlist}")
    print(f"      Songs to Download       : {len(tracks)}")
    print(f"      Target Folder           : {target_dir}")
    print(f"      Audio Quality           : {args.quality} kbps MP3 (Original 640x640 Cover Art)\n")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    print(f"[3/3] 🚀 Starting download...\n")

    for i, track in enumerate(tracks, start=1):
        title = track.get("title", f"Track_{i}")
        artist = track.get("artist", "Unknown Artist")
        album = track.get("album", "")
        thumbnail_url = track.get("thumbnail_url")
        search_query = f"{title} {artist}".strip()

        clean_file_name = f"{sanitize_name(artist)} - {sanitize_name(title)}.mp3"
        dest_path = target_dir / clean_file_name

        if dest_path.exists() and dest_path.stat().st_size > 500000:
            print(f"[{i}/{len(tracks)}] ⏭️  [SKIP] {clean_file_name} (Already downloaded)")
            skipped_count += 1
            continue

        print(f"[{i}/{len(tracks)}] ⏳ Downloading: {artist} - {title}")
        if thumbnail_url:
            print(f"       🖼️ Cover Art URL: {thumbnail_url[:65]}...")

        def on_progress(d):
            if d.get("status") == "downloading":
                pct = d.get("_percent_str", "0%").strip()
                speed = d.get("_speed_str", "").strip()
                print(f"       ⬇️  Progress: {pct} | Speed: {speed}", end="\r")

        result = download_song(
            query=search_query,
            output_dir=str(target_dir),
            quality=args.quality,
            thumbnail_url=thumbnail_url,
            title=title,
            artist=artist,
            album=album,
            progress_callback=on_progress
        )

        if result and os.path.exists(result):
            print(f"\n       ✅ [OK] Saved: {Path(result).name}")
            success_count += 1
        else:
            print(f"\n       ❌ [FAIL] Could not download: {title}")
            failed_count += 1

    print("\n" + "=" * 55)
    print(f"🎉 DOWNLOAD COMPLETE!")
    print(f"• Successfully Downloaded : {success_count}")
    print(f"• Skipped (Already Done)  : {skipped_count}")
    print(f"• Failed                  : {failed_count}")
    print(f"• Saved in                : {target_dir}")
    print("=" * 55)

if __name__ == "__main__":
    main()
