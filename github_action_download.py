"""
Headless Spotify Downloader & Gofile Uploader for GitHub Actions
Downloads songs in parts (e.g. 1000 songs), packs into a ZIP, uploads to Gofile, and notifies Telegram.
"""

import os
import sys
import re
import shutil
import zipfile
import requests
from pathlib import Path
from spotify_helper import fetch_universal_metadata, download_song

OUTPUT_DIR = Path("downloads")
QUALITY = os.getenv("QUALITY", "320")
GOFILE_API_TOKEN = os.getenv("GOFILE_API_TOKEN", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def sanitize_name(name: str) -> str:
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean or "Unknown"

def send_telegram_notification(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[Telegram Notification] {message}")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }, timeout=20)
    except Exception as e:
        print(f"[!] Failed to send Telegram notification: {e}")

def upload_to_gofile(file_path: Path, token: str = "") -> dict:
    """Uploads large file to Gofile API."""
    print(f"\n[Gofile] Getting best upload server...")
    try:
        server_resp = requests.get("https://api.gofile.io/servers", timeout=30).json()
        if server_resp.get("status") != "ok" or not server_resp.get("data", {}).get("servers"):
            server = "upload"
        else:
            server = server_resp["data"]["servers"][0]["name"]
    except Exception:
        server = "upload"

    upload_url = f"https://{server}.gofile.io/uploadfile"
    print(f"[Gofile] Uploading {file_path.name} ({file_path.stat().st_size / (1024*1024):.1f} MB) to {upload_url}...")

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(
                upload_url,
                files={"file": (file_path.name, f)},
                headers=headers,
                timeout=1800  # 30 minutes upload timeout
            )
        data = resp.json()
        if data.get("status") == "ok":
            dl_page = data.get("data", {}).get("downloadPage")
            file_id = data.get("data", {}).get("fileId")
            print(f"[Gofile] Upload successful! URL: {dl_page}")
            return {"url": dl_page, "fileId": file_id}
        else:
            print(f"[Gofile] Upload returned status: {data}")
            return {"error": data.get("message", "Upload error")}
    except Exception as e:
        print(f"[Gofile] Upload error: {e}")
        return {"error": str(e)}

def create_zip(folder_path: Path, zip_dest: Path):
    print(f"\n[Zip] Compressing folder '{folder_path.name}' into '{zip_dest.name}'...")
    with zipfile.ZipFile(zip_dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in folder_path.glob("*.mp3"):
            zf.write(file, arcname=file.name)
    print(f"[Zip] Created {zip_dest.name} ({zip_dest.stat().st_size / (1024*1024):.1f} MB)")

def main():
    playlist_url = os.getenv("PLAYLIST_URL", "").strip()
    part_num = int(os.getenv("PART_NUMBER", "1"))
    start_override = int(os.getenv("START_INDEX", "0"))
    end_override = int(os.getenv("END_INDEX", "0"))

    if not playlist_url:
        print("[!] No PLAYLIST_URL provided. Exiting.")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if start_override > 0 and end_override > 0:
        target_limit = end_override
    elif part_num > 0:
        target_limit = part_num * 1000
    else:
        target_limit = None

    print(f"[1/5] Fetching Spotify metadata: {playlist_url} (batch target: {target_limit or 'all'})")
    metadata = fetch_universal_metadata(playlist_url, max_tracks=target_limit)

    if not metadata or not metadata.get("tracks"):
        print("[!] Failed to fetch metadata. Exiting.")
        sys.exit(1)

    all_tracks = metadata["tracks"]
    total_in_playlist = len(all_tracks)
    title = sanitize_name(metadata.get("title", "Spotify_Playlist"))

    if start_override > 0 and end_override > 0:
        start_idx = max(1, start_override)
        end_idx = min(total_in_playlist, end_override)
        part_name = f"Custom_{start_idx}_to_{end_idx}"
    else:
        chunk_size = 1000
        start_idx = (part_num - 1) * chunk_size + 1
        end_idx = min(total_in_playlist, part_num * chunk_size)
        part_name = f"Part_{part_num}"

    selected_tracks = all_tracks[start_idx - 1 : end_idx]
    target_folder = OUTPUT_DIR / f"{title}_{part_name}"
    target_folder.mkdir(parents=True, exist_ok=True)

    print(f"\n[2/5] Target Part: {part_name} (Songs {start_idx} to {end_idx})")
    print(f"      Total Songs in this batch: {len(selected_tracks)}")
    print(f"      Audio Bitrate: {QUALITY} kbps MP3 with 640x640 cover art\n")

    send_telegram_notification(
        f"🚀 *GitHub Action Started!*\n\n"
        f"🎵 *Playlist:* `{title}`\n"
        f"📦 *Batch:* `{part_name}` (Songs {start_idx}–{end_idx})\n"
        f"⏳ Downloading in GitHub Cloud..."
    )

    success_count = 0
    failed_count = 0

    print(f"[3/5] Downloading songs...")
    for i, track in enumerate(selected_tracks, start=start_idx):
        t_title = track.get("title", f"Track_{i}")
        clean_name = re.split(r" - (?:Language|Film|Movie|Original|From)", t_title, flags=re.IGNORECASE)[0].strip()
        t_artist = track.get("artist", "")
        first_singer = t_artist.split(",")[0].strip()
        t_album = track.get("album", "")
        t_thumb = track.get("thumbnail_url")
        query = f"{clean_name} {first_singer}".strip()

        print(f"[{i}/{end_idx}] Downloading: {first_singer} - {clean_name}")
        res = download_song(
            query=query,
            output_dir=str(target_folder),
            quality=QUALITY,
            thumbnail_url=t_thumb,
            title=t_title,
            artist=t_artist,
            album=t_album,
            duration=track.get("duration")
        )
        if res and os.path.exists(res):
            success_count += 1
        else:
            failed_count += 1

    print(f"\n[4/5] Download finished: {success_count} succeeded, {failed_count} failed.")

    if success_count == 0:
        print("[!] No songs were successfully downloaded. Aborting upload.")
        send_telegram_notification(
            f"❌ *{part_name} Failed!*\n\n"
            f"🎵 *Playlist:* `{title}`\n"
            f"⚠️ 0 songs were downloaded."
        )
        sys.exit(1)

    # Compress into ZIP
    zip_path = OUTPUT_DIR / f"{title}_{part_name} @CinePrimeMusicBot.zip"
    create_zip(target_folder, zip_path)

    # Clean up uncompressed MP3s to free runner disk space
    shutil.rmtree(target_folder, ignore_errors=True)

    # Upload to Gofile
    print(f"\n[5/5] Uploading ZIP to Gofile...")
    upload_res = upload_to_gofile(zip_path, token=GOFILE_API_TOKEN)
    dl_url = upload_res.get("url")

    # Set GitHub Actions output
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"gofile_url={dl_url}\n")
            f.write(f"downloaded_count={success_count}\n")

    if dl_url:
        print("\n" + "=" * 60)
        print("🎉 SUCCESSFUL COMPLETION!")
        print(f"📁 Gofile Download Link: {dl_url}")
        print("=" * 60)

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.1f} MB"

        send_telegram_notification(
            f"✅ *{part_name} Download Completed!*\n\n"
            f"🎵 *Playlist:* `{title}`\n"
            f"📊 *Downloaded:* `{success_count}/{len(selected_tracks)} songs`\n"
            f"📦 *File Size:* `{size_str}`\n\n"
            f"🔗 *Gofile Link:* [Click Here to Download]({dl_url})\n\n"
            f"⚡ _Powered by CinePrime & GitHub Actions_"
        )
    else:
        print("[!] Failed to get Gofile download URL.")
        send_telegram_notification(f"⚠️ *{part_name}* completed downloading {success_count} songs, but Gofile upload failed.")

if __name__ == "__main__":
    main()
