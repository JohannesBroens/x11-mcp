"""AT-SPI accessibility tree reader.

Provides structured element data (roles, names, coordinates) from the
focused window. Used alongside screenshots for hybrid vision+structure
desktop automation.

Requires: at-spi2-core, gir1.2-atspi-2.0 (system packages).
"""

from __future__ import annotations

from typing import Optional

from x11_mcp.scaling import get_state

ROLE_ABBREV = {
    "push button": "btn",
    "toggle button": "toggle",
    "radio button": "radio",
    "check box": "checkbox",
    "text": "text_field",
    "password text": "password",
    "combo box": "combo",
    "menu": "menu",
    "menu item": "menu_item",
    "menu bar": "menubar",
    "tool bar": "toolbar",
    "tab": "tab",
    "page tab": "tab",
    "page tab list": "tablist",
    "scroll bar": "scrollbar",
    "slider": "slider",
    "spin button": "spin",
    "status bar": "statusbar",
    "label": "label",
    "icon": "icon",
    "image": "img",
    "link": "link",
    "list": "list",
    "list item": "list_item",
    "tree": "tree",
    "tree item": "tree_item",
    "table": "table",
    "table cell": "cell",
    "separator": "sep",
    "panel": "panel",
    "frame": "frame",
    "dialog": "dialog",
    "alert": "alert",
    "filler": "filler",
    "section": "section",
    "heading": "heading",
    "paragraph": "para",
    "document web": "web_doc",
    "document frame": "doc_frame",
}


def _atspi_available() -> bool:
    try:
        import gi
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
        Atspi.init()
        return True
    except Exception:
        return False


def _get_focused_accessible():
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi

    desktop = Atspi.get_desktop(0)
    n_apps = desktop.get_child_count()

    for i in range(n_apps):
        app = desktop.get_child_at_index(i)
        if app is None:
            continue
        n_windows = app.get_child_count()
        for j in range(n_windows):
            win = app.get_child_at_index(j)
            if win is None:
                continue
            try:
                state_set = win.get_state_set()
                if state_set.contains(Atspi.StateType.ACTIVE):
                    return win
            except Exception:
                continue
    return None


def _format_element(accessible, depth: int, max_depth: int, indent: int = 0) -> list[str]:
    if depth > max_depth:
        return []

    lines = []
    try:
        role = accessible.get_role_name()
        name = accessible.get_name() or ""
        role_abbr = ROLE_ABBREV.get(role, role.replace(" ", "_"))

        try:
            component = accessible.get_component_iface()
            if component:
                extent = component.get_extents(0)
                x, y, w, h = extent.x, extent.y, extent.width, extent.height
            else:
                x, y, w, h = 0, 0, 0, 0
        except Exception:
            x, y, w, h = 0, 0, 0, 0

        state = get_state()
        if w > 0 and h > 0:
            ax, ay = state.screen_to_api(x, y)
            aw = int(w * (state.api_size[0] / state.screen_size[0])) if state.screen_size[0] > 0 else w
            ah = int(h * (state.api_size[1] / state.screen_size[1])) if state.screen_size[1] > 0 else h
        else:
            ax, ay, aw, ah = x, y, w, h

        states = []
        try:
            state_set = accessible.get_state_set()
            import gi
            gi.require_version("Atspi", "2.0")
            from gi.repository import Atspi
            state_checks = [
                (Atspi.StateType.ENABLED, "enabled"),
                (Atspi.StateType.FOCUSED, "focused"),
                (Atspi.StateType.CHECKED, "checked"),
                (Atspi.StateType.SELECTED, "selected"),
                (Atspi.StateType.EDITABLE, "editable"),
                (Atspi.StateType.EXPANDABLE, "expandable"),
                (Atspi.StateType.EXPANDED, "expanded"),
                (Atspi.StateType.VISIBLE, "visible"),
            ]
            for st, label in state_checks:
                if state_set.contains(st):
                    states.append(label)
        except Exception:
            pass

        if "visible" not in states and w == 0 and h == 0:
            return []
        if role_abbr in ("filler", "panel", "section") and not name:
            n_children = accessible.get_child_count()
            for i in range(n_children):
                child = accessible.get_child_at_index(i)
                if child:
                    lines.extend(_format_element(child, depth + 1, max_depth, indent))
            return lines

        prefix = "  " * indent
        state_str = ",".join(s for s in states if s != "visible")
        coord_str = f"({ax}, {ay}, {aw}x{ah})" if aw > 0 else ""
        name_str = f' "{name}"' if name else ""

        line = f"{prefix}[{role_abbr}]{name_str} {coord_str}"
        if state_str:
            line += f" {state_str}"
        lines.append(line.rstrip())

        n_children = accessible.get_child_count()
        for i in range(n_children):
            child = accessible.get_child_at_index(i)
            if child:
                lines.extend(_format_element(child, depth + 1, max_depth, indent + 1))
    except Exception:
        pass

    return lines


def get_accessibility_tree(max_depth: int = 3) -> str:
    if not _atspi_available():
        return "[AT-SPI unavailable — falling back to vision-only mode]"

    focused = _get_focused_accessible()
    if focused is None:
        return "[No focused window found]"

    lines = _format_element(focused, depth=0, max_depth=max_depth)
    if not lines:
        return "[No accessible elements found in focused window]"

    max_lines = 200
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines.append(f"  ... ({len(lines)} elements shown, tree truncated at max_depth={max_depth})")

    return "\n".join(lines)


def find_element(query: str, max_depth: int = 5) -> str:
    if not _atspi_available():
        return "[AT-SPI unavailable — falling back to vision-only mode]"

    focused = _get_focused_accessible()
    if focused is None:
        return "[No focused window found]"

    matches = _search_tree(focused, query.lower(), depth=0, max_depth=max_depth)

    if not matches:
        return f'[No elements matching "{query}" found]'

    lines = []
    for role, name, x, y, w, h, states in matches:
        state = get_state()
        ax, ay = state.screen_to_api(x, y)
        aw = int(w * (state.api_size[0] / state.screen_size[0])) if state.screen_size[0] > 0 else w
        ah = int(h * (state.api_size[1] / state.screen_size[1])) if state.screen_size[1] > 0 else h

        role_abbr = ROLE_ABBREV.get(role, role.replace(" ", "_"))
        state_str = ",".join(states) if states else ""
        name_str = f' "{name}"' if name else ""
        line = f"[{role_abbr}]{name_str} ({ax}, {ay}, {aw}x{ah})"
        if state_str:
            line += f" {state_str}"
        cx, cy = ax + aw // 2, ay + ah // 2
        line += f" → click({cx}, {cy})"
        lines.append(line)

    return "\n".join(lines)


def _search_tree(
    accessible, query: str, depth: int, max_depth: int
) -> list[tuple[str, str, int, int, int, int, list[str]]]:
    if depth > max_depth:
        return []

    matches = []
    try:
        role = accessible.get_role_name()
        name = accessible.get_name() or ""
        desc = accessible.get_description() or ""

        if query in name.lower() or query in role.lower() or query in desc.lower():
            try:
                component = accessible.get_component_iface()
                if component:
                    extent = component.get_extents(0)
                    x, y, w, h = extent.x, extent.y, extent.width, extent.height
                else:
                    x, y, w, h = 0, 0, 0, 0
            except Exception:
                x, y, w, h = 0, 0, 0, 0

            states = []
            try:
                state_set = accessible.get_state_set()
                import gi
                gi.require_version("Atspi", "2.0")
                from gi.repository import Atspi
                for st, label in [
                    (Atspi.StateType.ENABLED, "enabled"),
                    (Atspi.StateType.FOCUSED, "focused"),
                    (Atspi.StateType.CHECKED, "checked"),
                    (Atspi.StateType.EDITABLE, "editable"),
                ]:
                    if state_set.contains(st):
                        states.append(label)
            except Exception:
                pass

            if w > 0 and h > 0:
                matches.append((role, name, x, y, w, h, states))

        n_children = accessible.get_child_count()
        for i in range(n_children):
            child = accessible.get_child_at_index(i)
            if child:
                matches.extend(_search_tree(child, query, depth + 1, max_depth))
    except Exception:
        pass

    return matches
