#!/bin/bash
# Double-click installer for macOS. First time: right-click this file > Open > Open (Apple's unidentified-developer check).
BASE="https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download"
DEST="$HOME/.video-context/src"
clear
echo "Understand This Video Plugin: installing."
echo "Please wait, this takes a few minutes."
echo
echo "A box will ask for your license key near the end."
mkdir -p "$DEST" && cd "$DEST" || exit 1
rm -rf video-context-ai
curl -fsSL "$BASE/video-context-ai.zip" -o plugin.zip || { osascript -e 'display dialog "Could not download the plugin." & return & return & "Check your internet and try again." with title "Understand This Video Plugin" buttons {"OK"} default button "OK"'; exit 1; }
unzip -qo plugin.zip && rm plugin.zip
bash video-context-ai/install.sh
echo; echo "You can close this window."
