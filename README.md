# 🎧 CinePrime Universal Music Telegram Bot

A multi-platform Telegram bot that downloads songs, playlists, and albums from Spotify, Apple Music, YouTube Music, JioSaavn, Wynk, and SoundCloud into high-quality MP3 audio files or ZIP archives with MongoDB Atlas caching and strict duplicate-free Database Channel archiving.

---

## 🌟 Key Features

1. **🌐 Multi-Platform Music Support**:
   - 🟢 **Spotify** (`open.spotify.com/...`)
   - 🔴 **YouTube / YouTube Music** (`music.youtube.com/...`)
   - 🍏 **Apple Music** (`music.apple.com/...`)
   - 🎵 **JioSaavn** (`jiosaavn.com/...`)
   - 🎶 **Wynk Music** (`wynk.in/...`)
   - 🟠 **SoundCloud** (`soundcloud.com/...`)

2. **🗄️ Database Channel Archiving (Strictly No Duplicates)**:
   - When a fresh song is downloaded, the bot sends it to the user AND uploads one copy to your Database Channel.
   - If the song is already in MongoDB / the Database Channel, the bot **does not upload a duplicate**; it sends the cached file directly to the user in 0.1 seconds!

3. **🍃 MongoDB Atlas Database**:
   - Every MP3 `file_id`, title, artist, audio duration, and channel message ID is permanently saved in MongoDB Atlas (`cineprime_music_bot`).

4. **🎚️ Audio Quality Switcher**:
   - Interactive buttons to select `⚡ 128k`, `🎧 192k` (Default), or `💎 320k` (Lossless).

5. **📦 Two Clean Formats**:
   - **`[ 📦 Download as ZIP File ]`**: Compresses all songs and uploads to Gofile cloud (with Catbox failover backup) for 1-click unlimited download.
   - **`[ 🎵 Download Single Songs ]`**: Delivers song by song directly in chat.

6. **🔍 Inline Search**:
   - Type `@CinePrimeMusicBot <song>` anywhere in Telegram to search and share music directly into groups or private chats.

7. **🖼️ Embedded Metadata**:
   - ID3 tags (Title, Artist) and high-resolution album cover art are embedded directly into each MP3 file.

---

## ⚙️ Configuration (`.env`)

```env
# Telegram Bot Token
TELEGRAM_BOT_TOKEN=9034699577:AAGP0n0YlK9qcgnxJeQTnFxoYqcbqS5DHac

# Gofile API Token
GOFILE_API_TOKEN=24toeK6ZvOLtHOLZdFDTso6zmz10AXrP

# MongoDB Atlas
MONGO_URI=mongodb+srv://dharani2006lakshmi_db_user:Byi5WDiKV6H53Xe1@cluster0.p93dbly.mongodb.net
MONGO_DB_NAME=cineprime_music_bot

# Force Subscribe Channel
FORCE_SUB_CHANNEL=@CineClick

# Database Channel ID (Add bot as admin in your channel)
# Example: @your_music_database or -100123456789
DUMP_CHANNEL_ID=
```
