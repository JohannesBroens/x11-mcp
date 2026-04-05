# x11-mcp

Native X11 MCP server for desktop automation on bare-metal Linux.
Direct capture via python-xlib, kernel-level input via python-uinput, hybrid vision + AT-SPI accessibility.

## Architecture

```
server.py          – MCP tool definitions (25 tools)
screenshot.py      – X11 framebuffer capture, JPEG encoding, primary monitor detection
scaling.py         – Singleton coordinate mapping (screen ↔ API space)
input.py           – Keyboard/mouse injection via /dev/uinput
window.py          – Window management via wmctrl + python-xlib fallback
accessibility.py   – AT-SPI tree reader for element discovery
```

## Key Design Decisions

- **Primary monitor by default**: Screenshots always capture the primary display, NOT the active window's monitor. This prevents capturing Claude's own display in multi-monitor setups.
- **Coordinate scaling**: Screenshots are downscaled to max 1280x800. All click/type coordinates are in this "API space" and automatically mapped back to screen space.
- **Compound tools**: `focus_and_capture()`, `click_and_verify()`, and `ensure_window_on_monitor()` wrap common multi-step patterns into single reliable calls.
- **wmctrl over xdotool**: Window focus/move uses wmctrl (no timeouts, handles decorations) with python-xlib fallback.
- **JPEG under 100KB**: Screenshots use adaptive JPEG quality (75→50→30) to stay within MCP token limits.

## Desktop Automation Workflow Pattern

When automating a desktop application:

1. `list_windows()` — find the target window ID
2. `focus_and_capture(name="...")` — move window to primary monitor + screenshot
3. Analyze the screenshot to identify click targets
4. `click_and_verify(x, y)` — click + get verification screenshot
5. Repeat 3-4 until the task is complete

**Never** assume a click succeeded without visual verification.
**Never** guess coordinates — always derive them from a recent screenshot.
**Always** use `focus_and_capture()` before first interaction with any window.

## Running Tests

```bash
# Unit tests (no X11 required, CI-safe)
pytest tests/ -m "not x11"

# Integration tests (requires live X11 display)
pytest tests/ -m x11
```

## E2E Testing

End-to-end tests verify the full automation loop using YAML specs:

```bash
# Run all E2E specs (requires X11 display)
python -m tests.e2e.runner

# Run smoke tests only
python -m tests.e2e.runner --tag smoke

# Run specific spec with verbose output
python -m tests.e2e.runner --spec 00-screenshot-basic -v

# Save JSON report
python -m tests.e2e.runner --report results.json
```

Specs live in `tests/e2e/specs/`. Add new specs as YAML files — see existing specs for format.

## Performance

Screenshots use MIT-SHM shared memory when available (~3x faster than X11 get_image).
The `capture_method` field in screenshot metadata reports which path was used ("xshm" or "get_image").

## Permission Configuration

### Claude Code CLI

For autonomous desktop automation, add to `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Bash(*:*)", "Mcp(*:*)"],
    "defaultMode": "bypassPermissions"
  }
}
```

### Claude Desktop

In `~/.config/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "x11-mcp": {
      "command": "/path/to/x11-mcp/.venv/bin/python",
      "args": ["-m", "x11_mcp"],
      "env": { "DISPLAY": ":0" }
    }
  },
  "preferences": {
    "bypassPermissionsModeEnabled": true
  }
}
```

## Development

- `install.sh` — creates venv, installs deps, prints MCP config
- `setup_uinput.sh` — one-time sudo setup for /dev/uinput kernel access
- Python 3.11+, dependencies in `pyproject.toml`
