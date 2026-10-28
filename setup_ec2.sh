#!/bin/bash
# ==============================================================================
# CinePrime Universal Music Telegram Bot - EC2 Setup & PM2 Service Runner
# ==============================================================================
set -e

echo "🎵 [MUSIC BOT] Installing system dependencies (ffmpeg, python3-pip)..."
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-pip

echo "📦 [MUSIC BOT] Installing Python dependencies..."
pip3 install -r requirements.txt --break-system-packages

echo "🚀 [MUSIC BOT] Starting bot with PM2..."
pm2 delete spotify-bot 2>/dev/null || true
pm2 start bot.py --name "spotify-bot" --interpreter python3
pm2 save

echo "✅ [MUSIC BOT] Successfully deployed & online!"
pm2 status
