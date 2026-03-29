from x11_mcp.input import parse_key_combo, char_to_key_events


class TestKeyParsing:
    def test_single_key(self):
        result = parse_key_combo("Return")
        assert result == ([], "Return")

    def test_ctrl_c(self):
        modifiers, key = parse_key_combo("ctrl+c")
        assert modifiers == ["ctrl"]
        assert key == "c"

    def test_ctrl_shift_t(self):
        modifiers, key = parse_key_combo("ctrl+shift+t")
        assert set(modifiers) == {"ctrl", "shift"}
        assert key == "t"

    def test_alt_tab(self):
        modifiers, key = parse_key_combo("alt+Tab")
        assert modifiers == ["alt"]
        assert key == "Tab"

    def test_single_letter(self):
        modifiers, key = parse_key_combo("a")
        assert modifiers == []
        assert key == "a"


class TestCharToKeyEvents:
    def test_lowercase(self):
        events = char_to_key_events("a")
        assert events == [("key", "a")]

    def test_uppercase(self):
        events = char_to_key_events("A")
        assert events == [("hold", "shift"), ("key", "a"), ("release", "shift")]

    def test_space(self):
        events = char_to_key_events(" ")
        assert events == [("key", "space")]

    def test_symbol_shift(self):
        events = char_to_key_events("!")
        assert events[0] == ("hold", "shift")
        assert events[-1] == ("release", "shift")

    def test_newline(self):
        events = char_to_key_events("\n")
        assert events == [("key", "Return")]

    def test_tab(self):
        events = char_to_key_events("\t")
        assert events == [("key", "Tab")]
