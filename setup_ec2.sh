#!/bin/bash
# ==============================================================================
# CinePrime Universal Music Telegram Bot - EC2 Setup & PM2 Service Runner
# ==============================================================================
set -e

echo "🎵 [MUSIC BOT] Installing system dependencies (ffmpeg, python3-pip, git)..."
sudo apt-get update -y
sudo apt-get install -y ffmpeg python3-pip git

# Ensure PM2 is installed
if ! command -v pm2 &> /dev/null; then
    echo "⚙️ [MUSIC BOT] PM2 not found. Installing Node.js & PM2..."
    sudo apt-get install -y nodejs npm
    sudo npm install -g pm2
fi

echo "📦 [MUSIC BOT] Installing Python dependencies..."
pip3 install -r requirements.txt --break-system-packages

echo "🚀 [MUSIC BOT] Starting bot with PM2..."
pm2 delete spotify-bot 2>/dev/null || true
pm2 start bot.py --name "spotify-bot" --interpreter python3
pm2 save

echo "✅ [MUSIC BOT] Successfully deployed & online!"
pm2 status
