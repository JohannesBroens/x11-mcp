# x11-mcp

> **⚠️ This software gives an AI the ability to see your screen, move your mouse, and type on your keyboard at the kernel level.** There is no sandbox. There is no simulation. Every action it takes is indistinguishable from your own — to your operating system, your applications, and your accounts. The moment you grant a machine uinput access and a framebuffer, the distinction between human and automated intent disappears from the perspective of everything downstream. Your window manager cannot tell the difference. Neither can your bank.
>
> A coordinate miscalculation clicks the wrong button. A misunderstood context types into the wrong window. The machine does not hesitate, does not double-check, and `Ctrl+Z` does not cover everything. We tend to think of computer control as reversible — but an email sent, a file overwritten, a dialog confirmed cannot be unsent, unwritten, or unconfirmed.
>
> **This is an experimental research project.** It exists to explore a question that will only become more pressing: what happens when AI can operate a computer the way we do? Not through constrained APIs, but through the same eyes and hands? The answer is both more capable and more dangerous than it appears. Do not run this on a system where unintended actions carry real consequences. The author develops on a dedicated workstation and accepts the risk. Treat this as a study in capability, not an invitation to trust.

---

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

## Ecosystem

x11-mcp is the foundation layer — eyes and hands for AI on a Linux desktop. It pairs with other projects that build on top of it:

| Project | Role |
|---------|------|
| **x11-mcp** | Desktop automation substrate (this repo) |
| **[x11-mcp-voice](https://github.com/JohannesBroens/x11-mcp-voice)** | Voice-controlled desktop agent via wake word + local STT/TTS |

## Requirements

- Linux with X11 (not Wayland)
- Python 3.10+
- `wmctrl`, `xdotool`, `xclip`

## License

MIT
