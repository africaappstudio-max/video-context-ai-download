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
    osascript -e 'text returned of (display dialog "Paste your license key (it is in your purchase email) and click OK." & return & return & "The plugin will not work without your license key." & return & return & "No key yet? Click Skip, then run this installer again when you have it." with title "Understand This Video Plugin" default answer "" buttons {"Skip","OK"} default button "OK" with icon note)' 2>/dev/null || true
  elif [ -r /dev/tty ]; then
    # /dev/tty works when this script is started with curl | bash (stdin is the pipe, not the keyboard).
    { printf '%s\n' "Paste your license key (it is in your purchase email) and press Enter."
      printf '\n'
      printf '%s\n' "The plugin will not work without your license key."
      printf '\n'
      printf '%s\n' "No key yet? Press Enter to skip, then run this installer again when you have it."
      printf '\n'
      printf '%s' "Key: "
    } > /dev/tty
    IFS= read -r K < /dev/tty || true
    printf '%s\n' "$K"
  fi
}
# Show a Mac dialog. Paragraphs (blank lines) or sentences become their own paragraph
# with a blank line between, using AppleScript "return & return" (argv newlines get lost).
as_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
as_body() {
  local text="$1" body="" sep="" para="" line chunk
  # If the text has no blank lines, split into sentences (". " / "? " / "! " before a capital).
  # (Do not use grep for blank lines: a pattern with a newline is treated as an empty pattern.)
  case "$text" in
    *$'\n\n'*) ;;
    *) text="$(printf '%s' "$text" | sed -E 's/([.?!])[ \t]+([A-Z])/\1\n\n\2/g')" ;;
  esac
  while IFS= read -r line || [ -n "$line" ]; do
    if [ -z "$line" ]; then
      if [ -n "$para" ]; then
        body="${body}${sep}\"$(as_esc "$para")\""
        sep=" & return & return & "
        para=""
      fi
    else
      if [ -n "$para" ]; then para="$para $line"; else para="$line"; fi
    fi
  done <<EOF
$text
EOF
  if [ -n "$para" ]; then
    body="${body}${sep}\"$(as_esc "$para")\""
  fi
  printf '%s' "$body"
}
note() {
  [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1 || return 0
  local body
  body="$(as_body "$1")"
  [ -n "$body" ] || return 0
  osascript -e "display dialog $body with title \"Understand This Video Plugin\" buttons {\"OK\"} default button \"OK\"" >/dev/null 2>&1 || true
}
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
  note $'Python 3.9 or newer is needed and could not be installed.\n\nPlease email video@shipmonthly.com.'; exit 1; }

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
  set +e
  ACT_MSG="$("$APP/bin/understand-this-video" activate "$KEY" 2>&1)"
  ACT_RC=$?
  set -e
  printf '%s\n' "$ACT_MSG"
  if [ "$ACT_RC" -eq 0 ]; then RESULT="ok"; else RESULT="badkey"; fi
else
  echo "You skipped the license key."
  echo
  echo "The plugin is installed, but it will not work until you run this installer again and paste the key from your purchase email."
  RESULT="nokey"
fi

# Download speech models if needed. Re-runs skip the download when they are already on this computer.
echo ""
echo "Checking the speech models..."
if ! "$APP/bin/understand-this-video" --warmup; then
  echo "Some downloads did not finish."
  echo
  echo "The plugin will finish them the first time you use it (it will just be slower once)."
fi

case "$RESULT" in
  ok)
    note $'All set!\n\nA folder called Understand This Video is now on your Desktop.\n\nPut your video in it.\n\nThen quit and reopen your AI app (Claude, Cursor...) and ask: Understand my latest video.\n\nThe first time, your Mac may ask if Claude can access your Desktop folder: click OK.' 
    [ "$(uname)" = "Darwin" ] && open "$VIDFOLDER" >/dev/null 2>&1 || true ;;
  badkey)
    note $'The license key was not accepted.\n\n'"${ACT_MSG}"$'\n\nThe plugin will not work without a valid key.\n\nIf this key has already been used on the maximum number of computers, deactivate it on one you no longer use, or email video@shipmonthly.com.'  ;;
  *)
    note $'The plugin is installed, but it is not activated yet because you skipped the license key.\n\nThe plugin will not work without it.\n\nRun this installer again and paste the key from your purchase email.\n\nThen quit and reopen your AI app.\n\nNo key yet? Get one at https://understandvideo.shipmonthly.com'  ;;
esac
echo "Done! Put your video in the \"Understand This Video\" folder on your Desktop, restart Claude Desktop / Cursor, then ask: \"Understand my latest video\"."
