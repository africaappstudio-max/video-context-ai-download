#!/usr/bin/env bash
# Understand This Video Plugin — one-line Mac installer.
# In Terminal, paste this and press Enter:
#   curl -fsSL https://understandvideo.shipmonthly.com/install.sh | bash
set -euo pipefail

say() { printf '%s\n' "$*"; }
as_esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
as_body() {
  local text="$1" body="" sep="" para="" line
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
fail() {
  say "$*" >&2
  if [ "$(uname)" = "Darwin" ] && command -v osascript >/dev/null 2>&1; then
    body="$(as_body "$1")"
    [ -n "$body" ] && osascript -e "display dialog $body with title \"Understand This Video Plugin\" buttons {\"OK\"} default button \"OK\"" >/dev/null 2>&1 || true
  fi
  exit 1
}

OS="$(uname)"
if [ "$OS" != "Darwin" ]; then
  if [ "$OS" = "Linux" ] && [ "${UTV_ALLOW_LINUX:-}" = "1" ]; then
    say "This installer is meant for Mac. Continuing because UTV_ALLOW_LINUX=1."
  else
    fail "This installer is for Mac.
If you are on Windows, download the Windows installer instead:
https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/Install-Understand-This-Video-Windows.bat
Need help? Email video@shipmonthly.com"
  fi
fi

command -v curl >/dev/null 2>&1 || fail "curl is needed and was not found. Email video@shipmonthly.com"
command -v unzip >/dev/null 2>&1 || fail "unzip is needed and was not found. Email video@shipmonthly.com"

ZIP_URL="https://github.com/africaappstudio-max/video-context-ai-download/releases/latest/download/video-context-ai.zip"
DEST="$HOME/.video-context/src"
mkdir -p "$DEST"
cd "$DEST"

say ""
say "Understand This Video Plugin"
say "Installing."
say "The first time, this also downloads the speech models (about 600 MB) so your first video is fast."
say "If you have installed before, that download is skipped."
say "Please leave this window open."
say ""
say "Downloading the plugin..."
TMP="$DEST/plugin.zip"
curl -fL --retry 3 --retry-delay 2 --progress-bar -o "$TMP" "$ZIP_URL" \
  || fail "Could not download the plugin. Check your internet and try again, or email video@shipmonthly.com."

say "Preparing the files..."
rm -rf "$DEST/video-context-ai"
unzip -qo "$TMP" -d "$DEST" || fail "Could not unpack the plugin. Please try again, or email video@shipmonthly.com."
rm -f "$TMP"

if [ -f "$DEST/video-context-ai/install.sh" ]; then
  INST="$DEST/video-context-ai/install.sh"
elif [ -f "$DEST/install.sh" ]; then
  INST="$DEST/install.sh"
else
  fail "The download looks incomplete. Please try again, or email video@shipmonthly.com."
fi

if [ "${UTV_STOP_AFTER:-}" = "download" ]; then
  say "Download and unpack finished (UTV_STOP_AFTER=download). Installer is at:"
  say "$INST"
  exit 0
fi

say "Installing (the first time this also downloads the speech models; later runs are quicker)..."
if [ "$OS" = "Darwin" ]; then
  say "A box will pop up near the end and ask for your license key."
  say "Paste it and click OK."
else
  say "When asked, paste your license key and press Enter."
fi
say ""

bash "$INST"
say ""
say "You can close this window."
