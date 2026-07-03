#!/bin/bash
# Double-click me. First run sets everything up (a few minutes); after that it just launches.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
  echo "Python 3 is required. macOS will offer to install developer tools -- accept, then run me again."
  xcode-select --install 2>/dev/null
  read -n 1 -s -r -p "Press any key to close..."
  exit 1
fi

if [ ! -d venv ]; then
  echo "First-time setup: creating environment and downloading dependencies..."
  echo "(this takes a few minutes and only happens once)"
  python3 -m venv venv || exit 1
  ./venv/bin/pip install --quiet --upgrade pip
  ./venv/bin/pip install -r requirements.txt || { echo "Install failed -- check your internet connection and try again."; exit 1; }
fi

if ! command -v ffmpeg >/dev/null; then
  echo ""
  echo "Note: ffmpeg not found -- MP3 files won't work (WAV/FLAC still fine)."
  echo "      To enable MP3:  brew install ffmpeg"
fi

if ! curl -s --max-time 2 http://localhost:11434/api/tags >/dev/null; then
  echo ""
  echo "Note: Ollama isn't running -- the chat Assistant will be disabled."
  echo "      To enable it: install from https://ollama.com, then run:  ollama pull gemma4:12b"
fi

echo ""
echo "Starting Stereo Splitter at http://localhost:5001 ..."
echo "(keep this window open; close it or press Ctrl+C to quit)"
(sleep 2 && open "http://localhost:5001") &
./venv/bin/python app.py
