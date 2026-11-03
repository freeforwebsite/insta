"""
CinePrime Local Web Player & Spotify Downloader
Runs locally on your PC. Play downloaded songs & download Spotify playlists directly in your browser.
"""

import os
import re
import glob
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from mutagen.mp3 import MP3

from spotify_helper import fetch_universal_metadata, download_song

app = FastAPI(title="CinePrime Local Web Player")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MUSIC_DIR = Path("D:/SpotifyMusic")
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

download_status = {
    "is_downloading": False,
    "should_stop": False,
    "current_song": "",
    "progress": "0%",
    "total": 0,
    "completed": 0,
    "log": []
}

def sanitize_name(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", name).strip() or "Unknown"

@app.get("/api/songs")
def list_songs():
    songs = []
    mp3_files = list(MUSIC_DIR.glob("**/*.mp3"))
    for idx, path in enumerate(mp3_files):
        title = path.stem
        artist = path.parent.name
        duration = 0
        has_cover = False
        has_lyrics = False
        try:
            audio = MP3(str(path))
            duration = int(audio.info.length)
            has_cover = any("APIC" in k for k in audio.tags.keys()) if audio.tags else False
            has_lyrics = any("USLT" in k for k in audio.tags.keys()) if audio.tags else False
            if audio.tags:
                if "TIT2" in audio.tags:
                    title = str(audio.tags["TIT2"])
                if "TPE1" in audio.tags:
                    artist = str(audio.tags["TPE1"])
        except Exception:
            pass

        rel_path = str(path.relative_to(MUSIC_DIR)).replace("\\", "/")
        songs.append({
            "id": idx,
            "title": title,
            "artist": artist,
            "duration": duration,
            "has_cover": has_cover,
            "has_lyrics": has_lyrics,
            "url": f"/stream/{rel_path}",
            "cover_url": f"/cover/{rel_path}" if has_cover else "",
            "folder": path.parent.name
        })
    return {"songs": songs, "total": len(songs)}

@app.get("/stream/{file_path:path}")
def stream_audio(file_path: str):
    full_path = MUSIC_DIR / file_path
    if full_path.exists():
        return FileResponse(str(full_path), media_type="audio/mpeg")
    return JSONResponse({"error": "File not found"}, status_code=404)

@app.get("/cover/{file_path:path}")
def get_cover(file_path: str):
    full_path = MUSIC_DIR / file_path
    if full_path.exists():
        try:
            audio = MP3(str(full_path))
            for k, v in audio.tags.items():
                if k.startswith("APIC"):
                    import io
                    return HTMLResponse(content=v.data, media_type="image/jpeg")
        except Exception:
            pass
    return JSONResponse({"error": "No cover"}, status_code=404)

@app.get("/api/status")
def get_status():
    return download_status

def run_download_task(url: str, limit: int = 0):
    global download_status
    download_status["is_downloading"] = True
    download_status["progress"] = "Fetching metadata..."
    download_status["log"].append(f"Starting fetch for: {url}")

    metadata = fetch_universal_metadata(url)
    if not metadata or not metadata.get("tracks"):
        download_status["is_downloading"] = False
        download_status["progress"] = "Failed to fetch metadata."
        return

    all_tracks = metadata["tracks"]
    tracks = all_tracks[:limit] if limit > 0 else all_tracks
    playlist_title = sanitize_name(metadata.get("title", "Spotify_Downloads"))
    target_dir = MUSIC_DIR / playlist_title
    target_dir.mkdir(parents=True, exist_ok=True)

    download_status["total"] = len(tracks)
    download_status["completed"] = 0
    download_status["should_stop"] = False

    for idx, track in enumerate(tracks, start=1):
        if download_status.get("should_stop"):
            download_status["is_downloading"] = False
            download_status["current_song"] = f"Paused at song {idx-1} of {len(tracks)}"
            download_status["progress"] = "Paused"
            return

        title = track.get("title", f"Track_{idx}")
        artist = track.get("artist", "")
        album = track.get("album", "")
        thumbnail_url = track.get("thumbnail_url")
        query = f"{title} {artist}".strip()

        download_status["current_song"] = f"[{idx}/{len(tracks)}] {title} - {artist}"
        download_status["progress"] = f"{int(((idx-1)/len(tracks))*100)}%"

        def on_prog(d):
            if d.get("status") == "downloading":
                download_status["progress"] = d.get("_percent_str", "0%").strip()

        download_song(
            query=query,
            output_dir=str(target_dir),
            quality="320",
            thumbnail_url=thumbnail_url,
            title=title,
            artist=artist,
            album=album,
            progress_callback=on_prog
        )
        download_status["completed"] = idx

    download_status["is_downloading"] = False
    download_status["progress"] = "Completed 100%"
    download_status["current_song"] = "All downloads finished!"

@app.post("/api/download")
def start_download(data: dict, bg_tasks: BackgroundTasks):
    url = data.get("url", "").strip()
    limit = int(data.get("limit", 0))
    if not url:
        return JSONResponse({"error": "URL required"}, status_code=400)
    bg_tasks.add_task(run_download_task, url, limit)
    return {"status": "started", "url": url, "limit": limit}

@app.post("/api/pause")
def pause_download():
    global download_status
    if download_status["is_downloading"]:
        download_status["should_stop"] = True
        return {"status": "pausing"}
    return {"status": "not_downloading"}

@app.get("/", response_class=HTMLResponse)
def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>CinePrime Music Hub</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0b0f19;
      --card: #151c2c;
      --accent: #1db954;
      --accent-hover: #1ed760;
      --text: #ffffff;
      --subtext: #8e9bb0;
      --border: #232d42;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: 'Plus Jakarta Sans', sans-serif; background: var(--bg); color: var(--text); padding: 24px; }
    .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
    .logo { font-size: 24px; font-weight: 800; color: var(--accent); display: flex; align-items: center; gap: 8px; }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 24px; }
    .input-row { display: flex; gap: 12px; margin-top: 12px; }
    input, select { background: #0c111d; border: 1px solid var(--border); color: white; padding: 12px 16px; border-radius: 10px; font-size: 14px; outline: none; }
    input:focus { border-color: var(--accent); }
    .btn { background: var(--accent); color: black; font-weight: 700; border: none; padding: 12px 24px; border-radius: 10px; cursor: pointer; transition: 0.2s; }
    .btn:hover { background: var(--accent-hover); transform: scale(1.02); }
    .song-list { display: grid; gap: 10px; }
    .song-item { display: flex; align-items: center; justify-content: space-between; background: #0c111d; padding: 12px 16px; border-radius: 12px; border: 1px solid var(--border); transition: 0.2s; }
    .song-item:hover { border-color: var(--accent); background: #131b2c; }
    .song-info { display: flex; align-items: center; gap: 14px; }
    .song-thumb { width: 52px; height: 52px; border-radius: 8px; object-fit: cover; background: #232d42; }
    .song-title { font-weight: 600; font-size: 15px; }
    .song-artist { font-size: 13px; color: var(--subtext); }
    .player-bar { position: fixed; bottom: 0; left: 0; right: 0; background: #111726; border-top: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; backdrop-filter: blur(10px); }
    audio { width: 450px; outline: none; }
  </style>
</head>
<body>
  <div class="header">
    <div class="logo">🎵 CinePrime Music Web Hub</div>
    <div id="stats" style="color: var(--subtext); font-size: 14px;">Loading local library...</div>
  </div>

  <div class="card">
    <h3>⬇️ Download From Spotify</h3>
    <div class="input-row">
      <input type="text" id="dl-url" placeholder="Paste Spotify Playlist or Song URL here..." style="flex: 1;">
      <select id="dl-limit">
        <option value="5">Test (5 Songs)</option>
        <option value="20">Top 20 Songs</option>
        <option value="50">Top 50 Songs</option>
        <option value="100">Top 100 Songs</option>
        <option value="0">All Songs</option>
      </select>
      <button class="btn" id="dl-btn" onclick="startDownload()">⬇️ Download</button>
      <button class="btn" id="pause-btn" style="background: #e74c3c; color: white; display: none;" onclick="pauseDownload()">⏸️ Pause</button>
    </div>
    <div id="dl-status" style="margin-top: 12px; font-size: 13px; color: var(--accent); display: none;"></div>
  </div>

  <div class="card">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <h3>📁 Local Music Library (D:\\SpotifyMusic)</h3>
      <button class="btn" style="padding: 8px 16px; font-size: 12px;" onclick="loadSongs()">🔄 Refresh Library</button>
    </div>
    <div class="song-list" id="songs-container">
      <div style="color: var(--subtext);">Loading your downloaded songs...</div>
    </div>
  </div>

  <div style="height: 100px;"></div>

  <div class="player-bar">
    <div style="display: flex; align-items: center; gap: 14px;">
      <img id="now-thumb" class="song-thumb" src="" style="display: none;">
      <div>
        <div id="now-title" style="font-weight: 700; font-size: 15px;">Select a song to play</div>
        <div id="now-artist" style="font-size: 13px; color: var(--subtext);">CinePrime Local Player</div>
      </div>
    </div>
    <audio id="audio-player" controls autoplay></audio>
  </div>

  <script>
    async function loadSongs() {
      try {
        const res = await fetch('/api/songs');
        const data = await res.json();
        document.getElementById('stats').innerText = `${data.total} Songs in D:\\\\SpotifyMusic`;
        const container = document.getElementById('songs-container');
        if (data.songs.length === 0) {
          container.innerHTML = '<div style="color: var(--subtext);">No songs found in D:\\\\SpotifyMusic yet. Download some above!</div>';
          return;
        }
        container.innerHTML = data.songs.map(s => `
          <div class="song-item">
            <div class="song-info">
              <img class="song-thumb" src="${s.cover_url || 'https://via.placeholder.com/52/151c2c/ffffff?text=MP3'}">
              <div>
                <div class="song-title">${s.title}</div>
                <div class="song-artist">${s.artist} ${s.has_lyrics ? '• 📝 Lyrics' : ''}</div>
              </div>
            </div>
            <button class="btn" style="padding: 8px 16px;" onclick="playSong('${s.url}', '${s.title.replace(/'/g, "\\'")}', '${s.artist.replace(/'/g, "\\'")}', '${s.cover_url}')">▶ Play</button>
          </div>
        `).join('');
      } catch (e) {
        console.error(e);
      }
    }

    function playSong(url, title, artist, cover) {
      const player = document.getElementById('audio-player');
      player.src = url;
      player.play();
      document.getElementById('now-title').innerText = title;
      document.getElementById('now-artist').innerText = artist;
      const thumb = document.getElementById('now-thumb');
      if (cover) {
        thumb.src = cover;
        thumb.style.display = 'block';
      } else {
        thumb.style.display = 'none';
      }
    }

    async function startDownload() {
      const url = document.getElementById('dl-url').value.trim();
      const limit = document.getElementById('dl-limit').value;
      if (!url) { alert('Please paste a Spotify URL'); return; }
      const statusDiv = document.getElementById('dl-status');
      const pauseBtn = document.getElementById('pause-btn');
      const dlBtn = document.getElementById('dl-btn');
      statusDiv.style.display = 'block';
      statusDiv.innerText = 'Starting download...';
      pauseBtn.style.display = 'inline-block';
      dlBtn.style.display = 'none';

      await fetch('/api/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url, limit: parseInt(limit) })
      });

      const interval = setInterval(async () => {
        const sRes = await fetch('/api/status');
        const s = await sRes.json();
        if (s.is_downloading) {
          statusDiv.innerText = `⏳ ${s.current_song} (${s.progress})`;
        } else {
          statusDiv.innerText = `✅ ${s.current_song}`;
          clearInterval(interval);
          pauseBtn.style.display = 'none';
          dlBtn.style.display = 'inline-block';
          loadSongs();
        }
      }, 1500);
    }

    async function pauseDownload() {
      const statusDiv = document.getElementById('dl-status');
      statusDiv.innerText = '⏸️ Pausing after current song completes...';
      await fetch('/api/pause', { method: 'POST' });
    }

    loadSongs();
  </script>
</body>
</html>
"""

if __name__ == "__main__":
    uvicorn.run("music_web:app", host="0.0.0.0", port=8888, reload=False)
