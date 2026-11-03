import os
import sys
import argparse
import re
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from redownload_missing import get_existing_song_names, normalize_title, DEFAULT_FOLDER
from spotify_helper import fetch_universal_metadata

MASTER_FOLDER = DEFAULT_FOLDER
NEW_FOLDER = Path(r"D:\SpotifyMusic\Tamil All Time Hits (1980 to 2026) 345+hours and 4500+ songs\new")

def main():
    parser = argparse.ArgumentParser(description="Export brand-new songs details from a Spotify playlist.")
    parser.add_argument("--url", default="https://open.spotify.com/playlist/7CcS1hPHyor4X6CXzNpPRy", help="Spotify playlist URL")
    args = parser.parse_args()

    print("=" * 65)
    print("🔍 SPOTIFY NEW SONGS FILTER & EXPORTER")
    print(f"📁 Master Library: {MASTER_FOLDER}")
    print("=" * 65)

    existing = get_existing_song_names(MASTER_FOLDER)
    if NEW_FOLDER.exists():
        existing |= get_existing_song_names(NEW_FOLDER)
    print(f"✓ Found {len(existing)} existing songs in your library.")

    print(f"\n[1/2] Fetching metadata from Spotify...")
    meta = fetch_universal_metadata(args.url, max_tracks=10000)
    tracks = meta.get("tracks", []) if meta else []
    p_title = meta.get("title", "Playlist") if meta else "Playlist"
    safe_title = re.sub(r'[\\/*?:"<>|]', '_', p_title)[:50].strip()
    print(f"✓ Loaded {len(tracks)} tracks from: {p_title}")

    new_songs = []
    seen = set()
    for t in tracks:
        norm = normalize_title(t.get("title", ""))
        if norm and norm not in existing and norm not in seen:
            seen.add(norm)
            new_songs.append(t)

    print("\n[2/2] Filter Results:")
    print(f"   ✓ Already in library / duplicates: {len(tracks) - len(new_songs)} songs filtered out")
    print(f"   🆕 Brand-New Songs Found:          {len(new_songs)} songs")

    out_txt = Path(r"D:\SpotifyMusic\Tamil All Time Hits (1980 to 2026) 345+hours and 4500+ songs") / f"{safe_title}_new_songs.txt"
    out_csv = Path(r"D:\SpotifyMusic\Tamil All Time Hits (1980 to 2026) 345+hours and 4500+ songs") / f"{safe_title}_new_songs.csv"

    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(f"=== {p_title} ({len(new_songs)} NEW Tracks) ===\n\n")
        for i, s in enumerate(new_songs, 1):
            f.write(f"{i}. {s.get('title')} | {s.get('artist')} | Album: {s.get('album', 'N/A')}\n")

    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("Index,Title,Artist,Album\n")
        for i, s in enumerate(new_songs, 1):
            t = (s.get("title") or "").replace('"', '""')
            a = (s.get("artist") or "").replace('"', '""')
            alb = (s.get("album") or "").replace('"', '""')
            f.write(f'{i},"{t}","{a}","{alb}"\n')

    print(f"\n📄 Saved details to:")
    print(f"   • Text file: {out_txt}")
    print(f"   • Excel CSV: {out_csv}")
    print("=" * 65)

if __name__ == "__main__":
    main()
