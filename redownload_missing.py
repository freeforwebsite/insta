"""
Missing Songs Re-Downloader for Spotify Playlists.
Scans your existing downloaded songs folder, identifies which tracks were skipped/failed,
and downloads only the missing songs directly to your folder using 10 parallel threads.
"""

import os
import sys
import re
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Set SKIP_LYRICS to prevent slow 10-second lrclib timeouts
os.environ.setdefault("SKIP_LYRICS", "1")

sys.path.insert(0, str(Path(__file__).parent))
from spotify_helper import fetch_universal_metadata, download_song

DEFAULT_FOLDER = Path(r"D:\SpotifyMusic\Tamil All Time Hits (1980 to 2026) 345+hours and 4500+ songs\3643 songs")
DEFAULT_URL = "https://open.spotify.com/playlist/7eMHkKCKwelg7afYViQMAf"

def normalize_title(text: str) -> str:
    clean = re.split(r" - (?:Language|Film|Movie|Original|From)", text, flags=re.IGNORECASE)[0].strip().lower()
    return re.sub(r"[^a-z0-9]", "", clean)

def get_existing_song_names(folder: Path) -> set:
    if not folder.exists():
        return set()
    names = set()
    for f in folder.glob("*.mp3"):
        names.add(normalize_title(f.stem))
    return names

def main():
    parser = argparse.ArgumentParser(description="Find and re-download missing Spotify songs.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Spotify playlist URL")
    parser.add_argument("--folder", default=str(DEFAULT_FOLDER), help="Master folder with existing songs to filter against")
    parser.add_argument("--save-to", default=None, help="New folder to save downloaded songs (optional, keeps playlists separate)")
    parser.add_argument("--limit", type=int, default=5000, help="Check up to song index (e.g. 5000 for all songs)")
    parser.add_argument("--workers", type=int, default=10, help="Parallel download threads")
    parser.add_argument("--quality", default="320", help="Audio quality bitrate")
    args = parser.parse_args()

    master_folder = Path(args.folder)
    dest_folder = Path(args.save_to) if args.save_to else master_folder
    dest_folder.mkdir(parents=True, exist_ok=True)

    print("=" * 65)
    print("🎵 SPOTIFY FILTER & DOWNLOADER")
    print(f"📁 Master Library (Filter): {master_folder}")
    if dest_folder != master_folder:
        print(f"💾 Save Destination:      {dest_folder}")
    print("=" * 65)

    existing_set = get_existing_song_names(master_folder)
    if dest_folder != master_folder and dest_folder.exists():
        existing_set |= get_existing_song_names(dest_folder)
    print(f"✓ Found {len(existing_set)} existing songs in your library to filter against.")

    print(f"\n[1/3] Fetching Spotify playlist metadata up to song #{args.limit}...")
    meta = fetch_universal_metadata(args.url, max_tracks=args.limit)
    if not meta or not meta.get("tracks"):
        print("[!] Could not fetch Spotify metadata. Check your internet connection.")
        return

    all_tracks = meta["tracks"][:args.limit]
    total_requested = len(all_tracks)
    print(f"✓ Loaded {total_requested} tracks from playlist.")

    missing_tracks = []
    seen_in_playlist = set()
    for i, t in enumerate(all_tracks, start=1):
        norm = normalize_title(t.get("title", ""))
        if norm and norm not in existing_set and norm not in seen_in_playlist:
            seen_in_playlist.add(norm)
            missing_tracks.append((i, t))

    print(f"\n[2/3] Comparison Results:")
    print(f"   ✓ Already in library / duplicates: {total_requested - len(missing_tracks)} songs filtered out")
    print(f"   🆕 Brand-new songs to download:     {len(missing_tracks)} songs")

    if not missing_tracks:
        print("\n🎉 All songs from this playlist are already in your library! Nothing new to download.")
        return

    print(f"\n[3/3] Starting parallel download of {len(missing_tracks)} new songs ({args.workers} concurrent threads)...")

    progress_lock = threading.Lock()
    completed = 0
    succeeded = 0
    failed = 0
    total_missing = len(missing_tracks)

    def worker(item):
        nonlocal completed, succeeded, failed
        idx, track = item
        t_title = track.get("title", f"Track_{idx}")
        # Strip (From ...), (Form ...), (feat ...), quotes, brackets, and extra movie tags
        clean_name = re.sub(r'[\(\[\{](?:From|Form|feat|with).*?[\)\]\}]', '', t_title, flags=re.IGNORECASE)
        clean_name = re.split(r" - (?:Language|Film|Movie|Original|From)", clean_name, flags=re.IGNORECASE)[0]
        clean_name = clean_name.replace('"', '').replace("'", "").replace(":", " ").strip()
        clean_name = re.sub(r'\s+', ' ', clean_name).strip()

        t_artist = track.get("artist", "")
        first_singer = t_artist.split(",")[0].strip()
        query = f"{clean_name} {first_singer}".strip()

        try:
            res = download_song(
                query=query,
                output_dir=str(dest_folder),
                quality=args.quality,
                thumbnail_url=track.get("thumbnail_url"),
                title=t_title,
                artist=t_artist,
                album=track.get("album"),
                duration=track.get("duration")
            )
            ok = bool(res and os.path.exists(res))
        except Exception:
            ok = False

        with progress_lock:
            completed += 1
            if ok:
                succeeded += 1
                icon = "✓"
            else:
                failed += 1
                icon = "✗"
            print(f"[{completed}/{total_missing}] {icon} (#{idx}) {first_singer} - {clean_name}")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(worker, item) for item in missing_tracks]
        for f in as_completed(futures):
            pass

    print("\n" + "=" * 65)
    print("🎉 DOWNLOAD COMPLETED!")
    print(f"   ✓ Newly Downloaded: {succeeded}")
    print(f"   ✗ Still Failed: {failed}")
    print(f"📁 All files saved to: {dest_folder}")
    print("=" * 65)

if __name__ == "__main__":
    main()
