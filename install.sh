#!/usr/bin/env bash
# Understand This Video Plugin installer for macOS (and Linux).
# Normally started by:  curl -fsSL https://understandvideo.shipmonthly.com/install.sh | bash
# Advanced users can run this file directly:  bash install.sh
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/.video-context/app"
mkdir -p "$HOME/.video-context"
LOG="$HOME/.video-context/install.log"
echo "== Understand This Video Plugin installer =="
echo "(details are saved to $LOG)"
exec > >(tee -a "$LOG") 2>&1

ask_key() {  # pop-up box on macOS, Terminal prompt otherwise. Key is never written to the log.
  if [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    osascript -e 'text returned of (display dialog "Paste your license key (it is in your purchase email) and click OK." & return & "No key yet? Click Skip and activate later." with title "Understand This Video Plugin" default answer "" buttons {"Skip","OK"} default button "OK" with icon note)' 2>/dev/null || true
  elif [ -r /dev/tty ]; then
    # /dev/tty works when this script is started with curl | bash (stdin is the pipe, not the keyboard).
    printf "Paste your license key (from your purchase email): " > /dev/tty
    IFS= read -r K < /dev/tty || true
    printf '%s\n' "$K"
  fi
}
note() { [ "$(uname)" = "Darwin" ] && osascript -e "display dialog \"$1\" with title \"Understand This Video Plugin\" buttons {\"OK\"} default button \"OK\"" >/dev/null 2>&1 || true; }

if [ "$(uname)" = "Darwin" ]; then
  if ! command -v ffmpeg >/dev/null 2>&1; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "Installing Homebrew (you may be asked for your Mac password in this window)..."
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
    fi
    echo "Installing ffmpeg..."; brew install ffmpeg
  fi
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
    command -v brew >/dev/null 2>&1 || eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
    echo "Installing Python..."; brew install python
  fi
else
  command -v ffmpeg >/dev/null 2>&1 || { echo "Installing ffmpeg..."; sudo apt-get update && sudo apt-get install -y ffmpeg; }
  command -v python3 >/dev/null 2>&1 || sudo apt-get install -y python3 python3-venv
fi

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  note "Python 3.9 or newer is needed and could not be installed. Please email video@shipmonthly.com."; exit 1; }

echo "Installing the plugin into $APP ..."
python3 -m venv "$APP"
"$APP/bin/pip" install -q --upgrade pip
"$APP/bin/pip" install -q "$HERE[all]"

VIDFOLDER="$HOME/Desktop/Understand This Video"
mkdir -p "$VIDFOLDER" 2>/dev/null || true

echo "Connecting your AI apps..."
"$APP/bin/python" "$HERE/register_mcp.py" "$APP/bin/understand-this-video-mcp"

KEY="${VIDEO_CONTEXT_LICENSE_KEY:-}"
[ -n "$KEY" ] || KEY="$(ask_key)"
RESULT=""
if [ -n "$KEY" ]; then
  if "$APP/bin/understand-this-video" activate "$KEY"; then RESULT="ok"; else RESULT="badkey"; fi
else
  echo "Later, activate with: $APP/bin/understand-this-video activate YOUR-KEY"
  RESULT="nokey"
fi

# Download everything the plugin needs NOW (speech models, test run), so your first video is fast.
echo ""
echo "Getting everything ready so your first video is fast (one time)."
echo "This downloads the speech models (about 600 MB in total) and can take several minutes on a slow connection."
if ! "$APP/bin/understand-this-video" --warmup; then
  echo "Some downloads did not finish. The plugin will finish them the first time you use it (it will just be slower once)."
fi

case "$RESULT" in
  ok)
    note "All set! A folder called Understand This Video is now on your Desktop. Put your video in it. Then quit and reopen your AI app (Claude, Cursor...) and ask: Understand my latest video. The first time, your Mac may ask if Claude can access your Desktop folder: click OK."
    [ "$(uname)" = "Darwin" ] && open "$VIDFOLDER" >/dev/null 2>&1 || true ;;
  badkey)
    note "The license key was not accepted. Check it and run this installer again, or email video@shipmonthly.com." ;;
  *)
    note "Installed. Run this installer again whenever you want to enter your license key." ;;
esac
echo "Done! Put your video in the \"Understand This Video\" folder on your Desktop, restart Claude Desktop / Cursor, then ask: \"Understand my latest video\"."
