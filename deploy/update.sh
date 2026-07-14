#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTALL_DIR="${1:-/opt/dhn-pi}"
RUN_PIP=false

for arg in "$@"; do
    [[ "$arg" == "--pip" ]] && RUN_PIP=true
done

if ! command -v ffmpeg &>/dev/null; then
    echo ">>> ffmpeg not found, installing..."
    sudo apt-get install -y -qq ffmpeg
fi

echo ">>> Updating from $PROJECT_DIR to $INSTALL_DIR..."
cp -r "$PROJECT_DIR"/* "$INSTALL_DIR/"
cp "$PROJECT_DIR/.env" "$INSTALL_DIR/" 2>/dev/null || true

if [ "$RUN_PIP" = true ]; then
    echo ">>> Reinstalling Python dependencies..."
    source "$INSTALL_DIR/venv/bin/activate"
    pip install -e "$INSTALL_DIR" -q
fi

echo ">>> Restarting service..."
sudo systemctl restart dhn-pi
echo "Done."
