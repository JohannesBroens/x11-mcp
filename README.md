# x11-mcp

Native X11 MCP server for desktop automation on bare-metal Linux. Direct framebuffer capture via python-xlib, kernel-level input via python-uinput, hybrid vision + AT-SPI accessibility.

Built for Claude Code. No Docker, no virtual displays.

## Install

```bash
git clone https://github.com/JohannesBroens/x11-mcp.git
cd x11-mcp
./install.sh        # creates venv, installs deps
./setup_uinput.sh   # one-time sudo setup for /dev/uinput
```

## Configure

**Claude Code** — add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "x11-mcp": {
      "command": "/path/to/x11-mcp/.venv/bin/python",
      "args": ["-m", "x11_mcp"]
    }
  }
}
```

## Usage

```
screenshot()                          # capture primary monitor
focus_and_capture(name="Firefox")     # move window to primary + screenshot
click_and_verify(x, y)               # click + verification screenshot
set_input_mode("xdotool")            # switch to XTest for Electron/CEF apps
open_app("YouTube Music")            # launch via desktop search
```

## Requirements

- Linux with X11 (not Wayland)
- Python 3.10+
- `wmctrl`, `xdotool`, `xclip`

## License

MIT
