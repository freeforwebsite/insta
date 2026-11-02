r"""
Local Spotify Playlist & Album Downloader for Windows PC
Downloads songs directly to your local drive (D:\SpotifyMusic\) with original 640x640 album covers & ID3 tags.
Supports downloading in parts (e.g. 1000 songs per part) and resume capability.
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
    parser.add_argument("--part", type=int, default=0, help="Part number (1 to 5, each ~1000 songs)")
    parser.add_argument("--start", type=int, default=0, help="Start song index (1-based)")
    parser.add_argument("--end", type=int, default=0, help="End song index (1-based)")
    parser.add_argument("--limit", type=int, default=0, help="Number of songs to download (e.g. 5 for testing)")
    parser.add_argument("--quality", default=DEFAULT_QUALITY, choices=["128", "192", "320"], help="Audio bitrate kbps")
    args = parser.parse_args()

    url = args.url.strip()
    if not url:
        url = input("🎵 Enter Spotify Playlist or Song URL: ").strip()

    if not url:
        print("[!] No URL provided. Exiting.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    target_limit = (args.part * 1000) if args.part > 0 else (args.end if args.end > 0 else None)
    print(f"\n[1/3] 🔍 Fetching playlist metadata for: {url}")
    metadata = fetch_universal_metadata(url, max_tracks=target_limit)

    if not metadata or not metadata.get("tracks"):
        print("[!] Failed to fetch playlist tracks. Please check your link.")
        return

    all_tracks = metadata["tracks"]
    total_in_playlist = len(all_tracks)

    start_idx = 1
    end_idx = total_in_playlist
    part_label = ""

    if args.part > 0:
        chunk_size = 1000
        start_idx = (args.part - 1) * chunk_size + 1
        end_idx = min(total_in_playlist, args.part * chunk_size)
        part_label = f"Part {args.part} (Songs {start_idx}-{end_idx})"
    elif args.start > 0 or args.end > 0:
        start_idx = max(1, args.start) if args.start > 0 else 1
        end_idx = min(total_in_playlist, args.end) if args.end > 0 else total_in_playlist
        part_label = f"Custom Range (Songs {start_idx}-{end_idx})"
    elif args.limit > 0:
        start_idx = 1
        end_idx = min(total_in_playlist, args.limit)
        part_label = f"First {end_idx} Songs"
    elif total_in_playlist > 1000:
        print(f"\n📊 Total songs found: {total_in_playlist}")
        print("Choose how you want to download:")
        print("  1. Part 1 (Songs 1 to 1000)      [~10 GB]")
        print("  2. Part 2 (Songs 1001 to 2000)   [~10 GB]")
        print("  3. Part 3 (Songs 2001 to 3000)   [~10 GB]")
        print("  4. Part 4 (Songs 3001 to 4000)   [~10 GB]")
        print("  5. Part 5 (Songs 4001 to end)    [~6 GB]")
        print("  6. All Songs (1 to 4595)         [~49 GB]")
        print("  7. Custom range (e.g. 1 to 100)")
        
        choice = input("\nEnter choice [1-7] (default 1): ").strip()
        if choice in ["1", "2", "3", "4", "5"]:
            p = int(choice)
            chunk_size = 1000
            start_idx = (p - 1) * chunk_size + 1
            end_idx = min(total_in_playlist, p * chunk_size)
            part_label = f"Part {p} (Songs {start_idx}-{end_idx})"
        elif choice == "6":
            start_idx = 1
            end_idx = total_in_playlist
            part_label = f"All {total_in_playlist} Songs"
        elif choice == "7":
            try:
                s_in = int(input("Start song number: ").strip())
                e_in = int(input("End song number: ").strip())
                start_idx = max(1, s_in)
                end_idx = min(total_in_playlist, e_in)
                part_label = f"Custom Range ({start_idx}-{end_idx})"
            except ValueError:
                start_idx = 1
                end_idx = 1000
                part_label = "Part 1 (Songs 1-1000)"
        else:
            start_idx = 1
            end_idx = min(total_in_playlist, 1000)
            part_label = "Part 1 (Songs 1-1000)"

    selected_tracks = all_tracks[start_idx - 1 : end_idx]
    playlist_title = sanitize_name(metadata.get("title", "Spotify_Playlist"))

    # Folder structure: D:\SpotifyMusic\<Playlist>\<Part>\
    if part_label and "Part" in part_label:
        target_dir = OUTPUT_DIR / playlist_title / part_label.split(" (")[0]
    else:
        target_dir = OUTPUT_DIR / playlist_title

    target_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[2/3] 📋 Playlist: '{metadata.get('title')}'")
    print(f"      Total in Playlist : {total_in_playlist}")
    print(f"      Downloading       : {part_label or f'Songs {start_idx} to {end_idx}'} ({len(selected_tracks)} songs)")
    print(f"      Target Folder     : {target_dir}")
    print(f"      Audio Quality     : {args.quality} kbps MP3 (Original 640x640 Covers)\n")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    print(f"[3/3] 🚀 Starting download...\n")

    for i, track in enumerate(selected_tracks, start=start_idx):
        title = track.get("title", f"Track_{i}")
        clean_title = re.split(r" - (?:Language|Film|Movie|Original|From)", title, flags=re.IGNORECASE)[0].strip()
        artist = track.get("artist", "Unknown Artist")
        first_singer = artist.split(",")[0].strip()
        album = track.get("album", "")
        thumbnail_url = track.get("thumbnail_url")
        search_query = f"{clean_title} {first_singer}".strip()

        clean_file_name = f"{sanitize_name(first_singer)} - {sanitize_name(clean_title)}.mp3"
        dest_path = target_dir / clean_file_name

        if dest_path.exists() and dest_path.stat().st_size > 500000:
            print(f"[{i}/{end_idx}] ⏭️  [SKIP] {clean_file_name} (Already exists)")
            skipped_count += 1
            continue

        print(f"[{i}/{end_idx}] ⏳ Downloading: {artist} - {title}")
        if thumbnail_url:
            print(f"       🖼️ Cover: {thumbnail_url[:60]}...")

        def on_progress(d):
            if d.get("status") == "downloading":
                pct = d.get("_percent_str", "0%").strip()
                speed = d.get("_speed_str", "").strip()
                print(f"       ⬇️  Progress: {pct} | Speed: {speed}", end="\r")

        duration = track.get("duration")

        result = download_song(
            query=search_query,
            output_dir=str(target_dir),
            quality=args.quality,
            thumbnail_url=thumbnail_url,
            title=title,
            artist=artist,
            album=album,
            duration=duration,
            progress_callback=on_progress
        )

        if result and os.path.exists(result):
            print(f"\n       ✅ [OK] Saved: {Path(result).name}")
            success_count += 1
        else:
            print(f"\n       ❌ [FAIL] Could not download: {title}")
            failed_count += 1

    print("\n" + "=" * 55)
    print(f"🎉 {part_label or 'DOWNLOAD'} COMPLETE!")
    print(f"• Successfully Downloaded : {success_count}")
    print(f"• Skipped (Already Done)  : {skipped_count}")
    print(f"• Failed                  : {failed_count}")
    print(f"• Saved in                : {target_dir}")
    print("=" * 55)

if __name__ == "__main__":
    main()
