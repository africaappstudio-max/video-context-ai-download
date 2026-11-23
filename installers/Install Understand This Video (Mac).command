#!/bin/bash
# Double-click installer for macOS. First time: right-click this file > Open > Open (Apple's unidentified-developer check).
VER="1.2.1"
BASE="https://github.com/africaappstudio-max/video-context-ai-download/releases/download/v$VER"
DEST="$HOME/.video-context/src"
clear
echo "Understand This Video Plugin: installing. Please wait, this takes a few minutes."
echo "A box will ask for your license key near the end."
mkdir -p "$DEST" && cd "$DEST" || exit 1
rm -rf video-context-ai
curl -fsSL "$BASE/video-context-ai.zip" -o plugin.zip || { osascript -e 'display dialog "Could not download the plugin. Check your internet and try again." buttons {"OK"}'; exit 1; }
unzip -qo plugin.zip && rm plugin.zip
bash video-context-ai/install.sh
echo; echo "You can close this window."
