#!/usr/bin/env bash
# One-time setup for python-uinput access.
# Run with: sudo bash setup_uinput.sh
set -euo pipefail

echo "=== x11-mcp: uinput setup ==="

modprobe uinput
echo "  [OK] uinput module loaded"

RULE='KERNEL=="uinput", MODE="0660", GROUP="input"'
echo "$RULE" > /etc/udev/rules.d/99-x11-mcp-uinput.rules
echo "  [OK] udev rule created"

REAL_USER="${SUDO_USER:-$USER}"
usermod -aG input "$REAL_USER"
echo "  [OK] User '$REAL_USER' added to input group"

udevadm control --reload-rules
udevadm trigger
echo "  [OK] udev rules reloaded"

echo ""
echo "=== Setup complete ==="
echo "IMPORTANT: You must log out and log back in for group changes to take effect."
echo "After logging back in, verify with: groups | grep input"
