#!/usr/bin/env bash
# Understand This Video For Me AI Plugin installer for macOS (and Linux). Run:  bash install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/.video-context/app"
echo "== Understand This Video For Me AI Plugin installer =="

if [ "$(uname)" = "Darwin" ]; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "Installing Homebrew (you may be asked for your Mac password)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
  fi
  command -v ffmpeg >/dev/null 2>&1 || { echo "Installing ffmpeg..."; brew install ffmpeg; }
  command -v python3 >/dev/null 2>&1 || brew install python
else
  command -v ffmpeg >/dev/null 2>&1 || { echo "Installing ffmpeg..."; sudo apt-get update && sudo apt-get install -y ffmpeg; }
  command -v python3 >/dev/null 2>&1 || sudo apt-get install -y python3 python3-venv
fi

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Python 3.9+ is required (macOS: brew install python)"; exit 1; }

echo "Installing Understand This Video For Me AI Plugin into $APP ..."
python3 -m venv "$APP"
"$APP/bin/pip" install -q --upgrade pip
"$APP/bin/pip" install -q "$HERE[all]"

echo "Registering with Claude Desktop and Cursor..."
"$APP/bin/python" "$HERE/register_mcp.py" "$APP/bin/understand-this-video-mcp"

KEY="${VIDEO_CONTEXT_LICENSE_KEY:-}"
if [ -z "$KEY" ] && [ -t 0 ]; then
  read -r -p "Paste your license key (from your purchase email): " KEY
fi
if [ -n "$KEY" ]; then
  "$APP/bin/understand-this-video" activate "$KEY"
else
  echo "Later, activate with: $APP/bin/understand-this-video activate YOUR-KEY"
fi
echo
echo "Done! Restart Claude Desktop / Cursor, then ask: \"Understand this video for me: ~/Desktop/My Video.mp4\"."
echo "Command line: $APP/bin/understand-this-video \"video.mp4\" --scene"
