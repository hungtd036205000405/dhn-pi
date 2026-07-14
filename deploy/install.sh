#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# install.sh - Install DHN-Pi on Linux with systemd auto-start
# Usage: sudo bash deploy/install.sh [/opt/dhn-pi]
# ---------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}>>>${NC} $1"; }
ok()   { echo -e "${GREEN}OK${NC}  $1"; }
err()  { echo -e "${RED}ERR${NC} $1"; exit 1; }

INSTALL_DIR="${1:-/opt/dhn-pi}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------------------------------------------------------------
# 1. Check root
# ---------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    err "This script must be run as root (for systemd + /opt install)."
fi

# ---------------------------------------------------------------
# 2. Check Python
# ---------------------------------------------------------------
log "Checking Python..."
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    err "Python not found. Install Python 3.11+ first."
fi

PYVER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ "$(echo "$PYVER >= 3.11" | bc)" != "1" ]]; then
    err "Python 3.11+ required, found $PYVER"
fi
ok "Python $PYVER found"

# ---------------------------------------------------------------
# 3. Install system dependencies
# ---------------------------------------------------------------
log "Installing system dependencies..."
apt-get update -qq
apt-get install -y -qq \
    python3-venv \
    python3-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    i2c-tools \
    || true  # non-critical on non-Pi

# ---------------------------------------------------------------
# 4. Copy project to install directory
# ---------------------------------------------------------------
log "Copying project to $INSTALL_DIR..."
if [[ -d "$INSTALL_DIR" ]]; then
    log "Removing existing installation..."
    rm -rf "$INSTALL_DIR"
fi
mkdir -p "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
cp -r "$PROJECT_DIR"/* "$INSTALL_DIR/"
cp "$PROJECT_DIR/.env" "$INSTALL_DIR/" 2>/dev/null || true

# ---------------------------------------------------------------
# 5. Create virtual environment
# ---------------------------------------------------------------
log "Creating virtual environment..."
$PYTHON -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
ok "Virtual environment created"

# ---------------------------------------------------------------
# 6. Install Python dependencies
# ---------------------------------------------------------------
log "Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q
pip install -e "$INSTALL_DIR" -q
ok "Python dependencies installed"

# ---------------------------------------------------------------
# 7. Install systemd service
# ---------------------------------------------------------------
log "Installing systemd service..."
cp "$INSTALL_DIR/deploy/dhn-pi.service" /etc/systemd/system/dhn-pi.service
sed -i "s|/opt/dhn-pi|$INSTALL_DIR|g" /etc/systemd/system/dhn-pi.service

# Set correct user
if id "pi" &>/dev/null; then
    SERVICE_USER="pi"
else
    SERVICE_USER="root"
fi
sed -i "s/User=pi/User=$SERVICE_USER/" /etc/systemd/system/dhn-pi.service
sed -i "s/Group=pi/Group=$SERVICE_USER/" /etc/systemd/system/dhn-pi.service

systemctl daemon-reload
systemctl enable dhn-pi
systemctl start dhn-pi
ok "systemd service installed and started"

# ---------------------------------------------------------------
# 8. Done
# ---------------------------------------------------------------
IP=$(hostname -I | awk '{print $1}')
echo ""
log "================================================"
log "DHN-Pi installed successfully!"
log "Install dir: $INSTALL_DIR"
log "Service:     sudo systemctl (start|stop|status|restart) dhn-pi"
log "Logs:        journalctl -u dhn-pi -f"
log "Web UI:      http://$IP:8000"
log "Swagger:     http://$IP:8000/docs"
log "================================================"
