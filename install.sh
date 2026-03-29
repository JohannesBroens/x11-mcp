#!/usr/bin/env bash
# Install x11-mcp and its dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== x11-mcp installer ==="

if [ -z "${DISPLAY:-}" ]; then
    echo "ERROR: No DISPLAY set. x11-mcp requires X11."
    exit 1
fi
echo "  [OK] X11 display: $DISPLAY"

PYTHON="python3"
if ! command -v "$PYTHON" &>/dev/null; then
    echo "ERROR: python3 not found"
    exit 1
fi
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  [OK] Python: $PY_VERSION"

echo ""
echo "Installing system packages (may need sudo)..."
sudo apt-get install -y wmctrl xclip at-spi2-core gir1.2-atspi-2.0 2>/dev/null || {
    echo "WARNING: Could not install system packages. Install manually:"
    echo "  sudo apt-get install wmctrl xclip at-spi2-core gir1.2-atspi-2.0"
}

echo ""
echo "Setting up Python environment..."
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
    echo "  [OK] Created .venv"
else
    echo "  [OK] .venv already exists"
fi

.venv/bin/pip install -e ".[dev]" --quiet
echo "  [OK] Installed x11-mcp and dependencies"

echo ""
echo "Verifying..."
.venv/bin/python -c "
import Xlib; print('  [OK] python-xlib')
import uinput; print('  [OK] python-uinput')
import PIL; print('  [OK] Pillow')
import mcp; print('  [OK] mcp')
import pydantic; print('  [OK] pydantic')
"

VENV_PYTHON="$(realpath .venv/bin/python)"
SERVER_MODULE="x11_mcp"

echo ""
echo "=== Add to ~/.claude/settings.json ==="
echo ""
cat <<JSONEOF
{
  "mcpServers": {
    "x11-mcp": {
      "command": "$VENV_PYTHON",
      "args": ["-m", "$SERVER_MODULE"],
      "env": {"DISPLAY": "$DISPLAY"}
    }
  }
}
JSONEOF

echo ""
echo "=== Add to permissions.allow ==="
echo '  "mcp__x11-mcp__*"'
echo ""
echo "=== Don't forget: sudo bash setup_uinput.sh ==="
echo ""
echo "Done!"
