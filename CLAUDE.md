# x11-mcp

Native X11 MCP server for desktop automation on bare-metal Linux.
Direct capture via python-xlib, kernel-level input via python-uinput, hybrid vision + AT-SPI accessibility.

## Architecture

```
server.py          – MCP tool definitions (28 tools)
screenshot.py      – X11 framebuffer capture (XShm + get_image), JPEG encoding, primary monitor detection
scaling.py         – Singleton coordinate mapping (screen ↔ API space)
input.py           – Dual input backends: UinputBackend (kernel) + XdotoolBackend (XTest/CEF)
_shm.py            – MIT-SHM shared memory for zero-copy screenshot capture
window.py          – Window management via wmctrl + python-xlib fallback
accessibility.py   – AT-SPI tree reader for element discovery
```

## Key Design Decisions

- **Primary monitor by default**: Screenshots always capture the primary display, NOT the active window's monitor. This prevents capturing Claude's own display in multi-monitor setups.
- **Coordinate scaling**: Screenshots are downscaled to max 1280x800. All click/type coordinates are in this "API space" and automatically mapped back to screen space.
- **Compound tools**: `focus_and_capture()`, `click_and_verify()`, and `ensure_window_on_monitor()` wrap common multi-step patterns into single reliable calls.
- **Dual input backends**: UinputBackend (fast, kernel-level) for native X11 apps. XdotoolBackend (XTest synthetic events) for CEF/Electron apps like Steam, Discord, VS Code. Switch with `set_input_mode("xdotool")`.
- **Window matching**: Searches both title AND WM_CLASS, so Electron apps (steamwebhelper, etc.) are findable by name.
- **App launcher**: `open_app("YouTube Music")` uses Super key + search — more reliable than clicking dock icons.
- **Click verification**: `click_and_verify()` detects new windows that appear after a click, enabling cleanup of misclicks.
- **wmctrl over xdotool for window ops**: Window focus/move uses wmctrl (no timeouts, handles decorations) with python-xlib fallback.
- **JPEG under 75KB**: Screenshots use adaptive JPEG quality (75→50→30) to stay within MCP limits.

## Desktop Automation Workflow Pattern

When automating a desktop application:

1. `open_app("App Name")` — open via desktop launcher (preferred), or `launch_app("command")` if you know the binary
2. `focus_and_capture(name="...")` — move window to primary monitor + screenshot
3. Analyze the screenshot to identify click targets
4. `click_and_verify(x, y)` — click + get verification screenshot (reports new_windows if something unexpected opened)
5. Repeat 3-4 until the task is complete

**For CEF/Electron apps** (Steam, Discord, VS Code): call `set_input_mode("xdotool")` before interacting. These apps need XTest synthetic events, not kernel uinput.

**Never** assume a click succeeded without visual verification.
**Never** guess coordinates — always derive them from a recent screenshot.
**Always** use `focus_and_capture()` before first interaction with any window.
**Always** use `open_app()` instead of clicking dock/taskbar icons to launch apps.

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
