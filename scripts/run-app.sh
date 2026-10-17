#!/bin/bash
# FoxProfile macOS app launcher.
# - Single instance: if the backend already runs, just focus the window.
# - Reaps orphan Flet windows and Chromium processes from previous runs so
#   the Dock never fills up with dead icons.
# Data lives in ~/.foxprofile (survives code updates).
export FOXPROFILE_PROFILES_FILE="$HOME/.foxprofile/profiles.json"
export FOXPROFILE_DATA_DIR="$HOME/.foxprofile/camoufox_data"
export FOXPROFILE_LOG_DIR="$HOME/.foxprofile/logs"
export FOXPROFILE_LANG="vi"

if pgrep -f "foxprofile/.venv/bin/python -m src.main" > /dev/null 2>&1; then
  open /Applications/FoxProfile.app 2>/dev/null || true
  exit 0
fi

# No backend alive: any Flet client or foxprofile-Chromium process is an orphan.
pkill -TERM -f ".flet/client/flet-desktop" 2>/dev/null || true
pkill -TERM -f "Library/Caches/foxprofile/chrome" 2>/dev/null || true
sleep 1

cd "$HOME/foxprofile" || exit 1
exec "$HOME/foxprofile/.venv/bin/python" -m src.main
