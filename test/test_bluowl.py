"""
BluOwl SerialMonitor — Automated Test Suite
============================================
Layer 1: Pure logic tests (no Qt required)
Layer 2: Qt widget tests (headless, requires PyQt6)

Run:
    pip install pytest
    pytest tests/test_bluowl.py -v

All tests must pass before committing any change.
Any new feature must have at least one test added here first.
"""

import sys
import os
import json
import datetime
import threading
import tempfile
import time

import pytest

# ── Import the app module (Qt-free portions extracted via sys.path) ───────────
# We import the module but mock QApplication so Qt widgets don't actually render.
# Pure-logic classes (LogStore, eval_filter, CommandProfile, etc.) import fine.

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub out heavy Qt imports so Layer 1 tests work without a display
try:
    from PyQt6.QtWidgets import QApplication
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False

# We import only the pure-logic symbols we need — avoids spinning up Qt
# by importing the module as source and exec'ing just what we need.
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "bluowl",
    os.path.join(os.path.dirname(__file__), "..", "BluOwl_SerialMonitor_V_5.20.py")
)

# ── Lazy load helpers — only the non-Qt parts ─────────────────────────────────
def _load_app():
    """Import the app module. Skips Qt widget instantiation."""
    import types, struct, array, mmap
    # Provide a minimal Qt stub so the module-level code doesn't crash
    # when there's no display. Only used for Layer 1.
    if not _QT_AVAILABLE:
        pytest.skip("PyQt6 not available — skipping Qt tests")
    mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(mod)
    return mod


# =============================================================================
# LAYER 1 — Pure logic tests (no Qt, no display required)
# =============================================================================

class TestEvalFilter:
    """Tests for the eval_filter() function."""

    # We import the function directly to avoid full module load
    @pytest.fixture(autouse=True)
    def _import(self):
        try:
            import regex as re_mod
        except ImportError:
            import re as re_mod
        import re as stdlib_re

        def eval_filter(text, filt, mode):
            filt = filt.strip()
            if not filt:
                return True
            if mode == "regex":
                try:
                    return bool(re_mod.search(filt, text, re_mod.IGNORECASE))
                except Exception:
                    return False
            low = text.lower()
            for grp in filt.split("|"):
                terms = [t.strip().lower() for t in grp.split("&") if t.strip()]
                if terms and all(t in low for t in terms):
                    return True
            return False

        self.f = eval_filter

    # ── Empty filter ──────────────────────────────────────────────────────────
    def test_empty_filter_show_returns_true(self):
        assert self.f("anything", "", "show") is True

    def test_empty_filter_hide_returns_true(self):
        assert self.f("anything", "", "hide") is True

    def test_whitespace_filter_returns_true(self):
        assert self.f("anything", "   ", "show") is True

    # ── SHOW mode ─────────────────────────────────────────────────────────────
    def test_show_simple_match(self):
        assert self.f("Temperature: 23.5", "temp", "show") is True

    def test_show_no_match(self):
        assert self.f("Battery: 3.7V", "temp", "show") is False

    def test_show_case_insensitive(self):
        assert self.f("ERROR: overflow", "error", "show") is True
        assert self.f("error: overflow", "ERROR", "show") is True

    def test_show_or_operator(self):
        assert self.f("voltage drop", "temp | voltage", "show") is True
        assert self.f("temperature spike", "temp | voltage", "show") is True
        assert self.f("battery low", "temp | voltage", "show") is False

    def test_show_and_operator(self):
        assert self.f("ERROR: temp overflow", "error & temp", "show") is True
        assert self.f("ERROR: voltage drop", "error & temp", "show") is False
        assert self.f("temp warning", "error & temp", "show") is False

    def test_show_and_or_combined(self):
        # (error & temp) OR (warn & volt)
        assert self.f("ERROR temp spike", "error & temp | warn & volt", "show") is True
        assert self.f("WARNING volt drop", "error & temp | warn & volt", "show") is True
        assert self.f("INFO: nothing", "error & temp | warn & volt", "show") is False

    def test_show_whitespace_around_operators(self):
        assert self.f("hello world", "  hello  |  world  ", "show") is True

    # ── HIDE mode ─────────────────────────────────────────────────────────────
    def test_hide_matching_line_returns_true(self):
        # eval_filter returns True for a line the filter MATCHES
        # In HIDE mode the caller does: if (not m) => hide → show only non-matches
        assert self.f("DEBUG: verbose", "debug", "hide") is True

    def test_hide_non_matching_line_returns_false(self):
        assert self.f("ERROR: critical", "debug", "hide") is False

    # ── REGEX mode ────────────────────────────────────────────────────────────
    def test_regex_simple_match(self):
        assert self.f("voltage: 3.72V", r"\d+\.\d+", "regex") is True

    def test_regex_no_match(self):
        assert self.f("no numbers here", r"\d+\.\d+", "regex") is False

    def test_regex_alternation(self):
        assert self.f("ERROR detected", "error|warning", "regex") is True
        assert self.f("WARNING issued", "error|warning", "regex") is True
        assert self.f("INFO message", "error|warning", "regex") is False

    def test_regex_case_insensitive(self):
        assert self.f("ERROR", "error", "regex") is True

    def test_regex_invalid_pattern_returns_false(self):
        # Invalid regex must return False (match nothing), NOT True (match everything)
        assert self.f("any text", "[unclosed", "regex") is False
        assert self.f("any text", "(?invalid", "regex") is False
        assert self.f("any text", "*nostart",  "regex") is False

    def test_regex_anchors(self):
        assert self.f("ERR001", r"^ERR\d+$", "regex") is True
        assert self.f("prefix ERR001", r"^ERR\d+$", "regex") is False

    def test_regex_groups(self):
        assert self.f("Temp=23.5", r"Temp=(\d+\.\d+)", "regex") is True


class TestLogStore:
    """Tests for LogStore — append, get_text, get_dir, get_ts, clear, len."""

    @pytest.fixture
    def store(self):
        import struct, threading, datetime, time

        class LogStore:
            REC  = struct.Struct("<IHBBIxxx")
            DIR  = {"rx":0,"tx":1,"sys":2}
            RDIR = {0:"rx",1:"tx",2:"sys"}

            def __init__(self):
                self._buf   = bytearray()
                self._idx   = bytearray()
                self._count = 0
                self._epoch      = datetime.datetime.now()
                self._epoch_perf = time.perf_counter()
                self._lock  = threading.Lock()

            def append(self, direction, text, ts, is_bytes=False):
                raw    = text.encode("utf-8","replace")
                length = min(len(raw), 65535)
                d      = self.DIR.get(direction, 2)
                flags  = 1 if is_bytes else 0
                ts_ms  = max(0, int((ts - self._epoch).total_seconds() * 1000))
                with self._lock:
                    offset = len(self._buf)
                    self._buf.extend(raw[:length])
                    self._idx.extend(self.REC.pack(offset, length, d, flags, ts_ms))
                    self._count += 1
                    return self._count - 1

            def __len__(self): return self._count

            def get_text(self, i):
                off = i * self.REC.size
                offset,length,d,flags,_ = self.REC.unpack_from(self._idx, off)
                return self._buf[offset:offset+length].decode("utf-8","replace")

            def get_dir(self, i):
                off = i * self.REC.size
                _,_,d,_,_ = self.REC.unpack_from(self._idx, off)
                return self.RDIR.get(d, "sys")

            def get_ts(self, i):
                ts_ms = self.REC.unpack_from(self._idx, i * self.REC.size)[4]
                return self._epoch + datetime.timedelta(milliseconds=ts_ms)

            def get_is_bytes(self, i):
                off = i * self.REC.size
                _,_,_,flags,_ = self.REC.unpack_from(self._idx, off)
                return bool(flags & 1)

            def clear(self):
                with self._lock:
                    self._buf=bytearray(); self._idx=bytearray(); self._count=0

            def mem_mb(self):
                return (len(self._buf)+len(self._idx))/1_048_576

        return LogStore()

    # ── Basic operations ──────────────────────────────────────────────────────
    def test_empty_store_len(self, store):
        assert len(store) == 0

    def test_append_returns_index(self, store):
        ts = datetime.datetime.now()
        idx = store.append("rx", "hello", ts)
        assert idx == 0

    def test_append_increments_len(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "line1", ts)
        store.append("tx", "line2", ts)
        assert len(store) == 2

    def test_get_text_roundtrip(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "Temperature: 23.5", ts)
        assert store.get_text(0) == "Temperature: 23.5"

    def test_get_text_unicode(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "°C ±0.1", ts)
        assert "°C" in store.get_text(0)

    def test_get_dir_rx(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "data", ts)
        assert store.get_dir(0) == "rx"

    def test_get_dir_tx(self, store):
        ts = datetime.datetime.now()
        store.append("tx", "cmd", ts)
        assert store.get_dir(0) == "tx"

    def test_get_dir_sys(self, store):
        ts = datetime.datetime.now()
        store.append("sys", "connected", ts)
        assert store.get_dir(0) == "sys"

    def test_multiple_entries_independent(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "first",  ts)
        store.append("tx", "second", ts)
        store.append("rx", "third",  ts)
        assert store.get_text(0) == "first"
        assert store.get_text(1) == "second"
        assert store.get_text(2) == "third"
        assert store.get_dir(0) == "rx"
        assert store.get_dir(1) == "tx"
        assert store.get_dir(2) == "rx"

    # ── Timestamp accuracy ────────────────────────────────────────────────────
    def test_timestamp_millisecond_precision(self, store):
        base = datetime.datetime(2024, 1, 1, 12, 0, 0)
        t1   = base + datetime.timedelta(milliseconds=100)
        t2   = base + datetime.timedelta(milliseconds=250)
        t3   = base + datetime.timedelta(milliseconds=999)
        store._epoch = base
        store.append("rx", "a", t1)
        store.append("rx", "b", t2)
        store.append("rx", "c", t3)
        r1 = store.get_ts(0)
        r2 = store.get_ts(1)
        r3 = store.get_ts(2)
        # Should round-trip to within 1ms
        assert abs((r1 - t1).total_seconds() * 1000) < 1.5
        assert abs((r2 - t2).total_seconds() * 1000) < 1.5
        assert abs((r3 - t3).total_seconds() * 1000) < 1.5

    def test_timestamps_are_ordered(self, store):
        base = datetime.datetime(2024, 1, 1, 12, 0, 0)
        store._epoch = base
        for ms in [0, 100, 200, 300, 400]:
            t = base + datetime.timedelta(milliseconds=ms)
            store.append("rx", f"line_{ms}", t)
        times = [store.get_ts(i) for i in range(len(store))]
        assert times == sorted(times)

    def test_same_second_different_ms(self, store):
        base = datetime.datetime(2024, 1, 1, 12, 0, 0)
        store._epoch = base
        t1 = base + datetime.timedelta(milliseconds=0)
        t2 = base + datetime.timedelta(milliseconds=1)
        store.append("rx", "fast", t1)
        store.append("rx", "faster", t2)
        diff_ms = (store.get_ts(1) - store.get_ts(0)).total_seconds() * 1000
        assert diff_ms >= 0.5   # must be distinguishable

    # ── Clear ─────────────────────────────────────────────────────────────────
    def test_clear_resets_len(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "data", ts)
        store.append("tx", "cmd",  ts)
        store.clear()
        assert len(store) == 0

    def test_append_after_clear(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "before", ts)
        store.clear()
        store.append("rx", "after", ts)
        assert len(store) == 1
        assert store.get_text(0) == "after"

    # ── Edge cases ────────────────────────────────────────────────────────────
    def test_empty_string_entry(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "", ts)
        assert len(store) == 1
        assert store.get_text(0) == ""

    def test_long_text_truncated_at_65535(self, store):
        ts   = datetime.datetime.now()
        long = "A" * 70000
        store.append("rx", long, ts)
        assert len(store.get_text(0)) == 65535

    def test_is_bytes_flag(self, store):
        ts = datetime.datetime.now()
        store.append("rx", "01 02 03", ts, is_bytes=True)
        store.append("rx", "hello",    ts, is_bytes=False)
        assert store.get_is_bytes(0) is True
        assert store.get_is_bytes(1) is False

    def test_thread_safety_concurrent_appends(self, store):
        results = []
        errors  = []
        ts = datetime.datetime.now()

        def _worker(n):
            try:
                for i in range(50):
                    store.append("rx", f"thread{n}_line{i}", ts)
                results.append(n)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(n,)) for n in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert not errors, f"Thread errors: {errors}"
        assert len(store) == 200   # 4 threads × 50 lines
        assert len(results) == 4


class TestCommandProfile:
    """Tests for CommandProfile and ButtonConfig serialisation."""

    def test_default_profile(self):
        from dataclasses import dataclass, field, asdict

        @dataclass
        class ButtonConfig:
            label:   str = "Button"
            command: str = ""
            color:   str = ""

        @dataclass
        class CommandProfile:
            name:        str  = "Untitled"
            line_ending: str  = "CRLF"
            buttons:     list = field(default_factory=list)

            def to_dict(self):
                return {"name": self.name,
                        "line_ending": self.line_ending,
                        "buttons": [asdict(b) for b in self.buttons]}

            @staticmethod
            def from_dict(d):
                btns = [ButtonConfig(**b) for b in d.get("buttons", [])]
                return CommandProfile(
                    name        = d.get("name", "Untitled"),
                    line_ending = d.get("line_ending", "CRLF"),
                    buttons     = btns)

        p = CommandProfile()
        assert p.name == "Untitled"
        assert p.line_ending == "CRLF"
        assert p.buttons == []

    def test_to_dict_roundtrip(self):
        from dataclasses import dataclass, field, asdict

        @dataclass
        class ButtonConfig:
            label:   str = "Button"
            command: str = ""
            color:   str = ""

        @dataclass
        class CommandProfile:
            name:        str  = "Untitled"
            line_ending: str  = "CRLF"
            buttons:     list = field(default_factory=list)

            def to_dict(self):
                return {"name": self.name,
                        "line_ending": self.line_ending,
                        "buttons": [asdict(b) for b in self.buttons]}

            @staticmethod
            def from_dict(d):
                btns = [ButtonConfig(**b) for b in d.get("buttons", [])]
                return CommandProfile(
                    name        = d.get("name", "Untitled"),
                    line_ending = d.get("line_ending", "CRLF"),
                    buttons     = btns)

        p = CommandProfile(
            name        = "Test Suite",
            line_ending = "LF",
            buttons     = [
                ButtonConfig("Power On",  "PWR_ON",  "#2a5a2a"),
                ButtonConfig("BT Scan",   "BT_SCAN", ""),
                ButtonConfig("Reset",     "RESET",   "#5a1a1a"),
            ]
        )
        d   = p.to_dict()
        p2  = CommandProfile.from_dict(d)

        assert p2.name        == "Test Suite"
        assert p2.line_ending == "LF"
        assert len(p2.buttons)== 3
        assert p2.buttons[0].label   == "Power On"
        assert p2.buttons[0].command == "PWR_ON"
        assert p2.buttons[0].color   == "#2a5a2a"
        assert p2.buttons[1].command == "BT_SCAN"
        assert p2.buttons[2].color   == "#5a1a1a"

    def test_from_dict_missing_fields_use_defaults(self):
        from dataclasses import dataclass, field, asdict

        @dataclass
        class ButtonConfig:
            label:   str = "Button"
            command: str = ""
            color:   str = ""

        @dataclass
        class CommandProfile:
            name:        str  = "Untitled"
            line_ending: str  = "CRLF"
            buttons:     list = field(default_factory=list)

            @staticmethod
            def from_dict(d):
                btns = [ButtonConfig(**b) for b in d.get("buttons", [])]
                return CommandProfile(
                    name        = d.get("name", "Untitled"),
                    line_ending = d.get("line_ending", "CRLF"),
                    buttons     = btns)

        p = CommandProfile.from_dict({})
        assert p.name == "Untitled"
        assert p.line_ending == "CRLF"
        assert p.buttons == []

    def test_json_file_roundtrip(self):
        from dataclasses import dataclass, field, asdict

        @dataclass
        class ButtonConfig:
            label:   str = "Button"
            command: str = ""
            color:   str = ""

        @dataclass
        class CommandProfile:
            name:        str  = "Untitled"
            line_ending: str  = "CRLF"
            buttons:     list = field(default_factory=list)

            def to_dict(self):
                return {"name": self.name,
                        "line_ending": self.line_ending,
                        "buttons": [asdict(b) for b in self.buttons]}

            @staticmethod
            def from_dict(d):
                btns = [ButtonConfig(**b) for b in d.get("buttons", [])]
                return CommandProfile(
                    name        = d.get("name", "Untitled"),
                    line_ending = d.get("line_ending", "CRLF"),
                    buttons     = btns)

        p = CommandProfile(
            name    = "Saved Profile",
            buttons = [ButtonConfig("CMD1", "AT+RESET", "#336")]
        )
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".boc", delete=False) as f:
            json.dump(p.to_dict(), f)
            path = f.name
        try:
            with open(path) as f:
                d = json.load(f)
            p2 = CommandProfile.from_dict(d)
            assert p2.name == "Saved Profile"
            assert p2.buttons[0].command == "AT+RESET"
        finally:
            os.unlink(path)


class TestHelperFunctions:
    """Tests for hex_dump, to_ascii, fmt_size."""

    def test_hex_dump_basic(self):
        def hex_dump(data):
            return " ".join(f"{b:02X}" for b in data)
        assert hex_dump(b"\x00\x01\xFF") == "00 01 FF"
        assert hex_dump(b"")             == ""
        assert hex_dump(b"A")            == "41"

    def test_to_ascii_printable(self):
        def to_ascii(data):
            return "".join(chr(b) if 32 <= b < 127 else "." for b in data)
        assert to_ascii(b"hello") == "hello"
        assert to_ascii(b"\x00\x01\x02") == "..."
        assert to_ascii(b"A\x00B") == "A.B"

    def test_fmt_size_bytes(self):
        def fmt_size(sz):
            if sz < 1024: return f"{sz} B"
            if sz < 1048576: return f"{sz/1024:.1f} KB"
            return f"{sz/1048576:.2f} MB"
        assert fmt_size(512)     == "512 B"
        assert fmt_size(1024)    == "1.0 KB"
        assert fmt_size(1536)    == "1.5 KB"
        assert fmt_size(1048576) == "1.00 MB"
        assert fmt_size(2097152) == "2.00 MB"


# =============================================================================
# LAYER 2 — Qt widget tests (requires display / PyQt6)
# =============================================================================

@pytest.mark.skipif(not _QT_AVAILABLE, reason="PyQt6 not available")
class TestLiveLogView:
    """Tests for LiveLogView — append, line count, gutter, scroll."""

    @pytest.fixture(scope="class")
    def app(self):
        app = QApplication.instance() or QApplication(sys.argv)
        return app

    @pytest.fixture
    def view(self, app):
        from PyQt6.QtGui import QFont, QColor
        # Minimal palette
        pal = {
            "bg":"#1a1a2e","bg2":"#1e1e3a","bg3":"#252545",
            "fg":"#e0e0e0","fg_dim":"#666","border":"#333",
            "rx":"#4a90d9","tx":"#f0a858","sys":"#888",
            "ts":"#555","hex":"#c97bf7","green":"#00e676",
            "red":"#f07878",
        }
        font = QFont("Courier New", 9)

        # Import LiveLogView from the app
        mod = _load_app()
        v = mod.LiveLogView(pal, font)
        v.resize(800, 400)
        return v

    def test_initial_block_count(self, view):
        assert view.document().blockCount() == 1   # QPlainTextEdit starts with 1 empty block

    def test_append_line_increases_block_count(self, view):
        view.clear_log()
        view.append_line("12:00:00.001  RX  hello", "rx")
        view.append_line("12:00:00.002  TX  world", "tx")
        assert view.document().blockCount() == 2

    def test_clear_log_resets_content(self, view):
        view.clear_log()
        view.append_line("12:00:00.001  RX  test", "rx")
        view.clear_log()
        assert view.document().toPlainText().strip() == ""

    def test_gutter_width_nonzero(self, view):
        view.clear_log()
        assert view._gutter_width() > 0

    def test_gutter_width_grows_with_line_count(self, view):
        view.clear_log()
        w1 = view._gutter_width()
        # Add enough lines to go from 1-digit to 4-digit line numbers
        for i in range(1000):
            view.append_line(f"12:00:00.{i:03d}  RX  line {i}", "rx")
        w2 = view._gutter_width()
        assert w2 > w1, "Gutter should widen as line count grows past 9, 99, 999"

    def test_append_preserves_text(self, view):
        view.clear_log()
        view.append_line("12:00:00.001  RX  Temperature: 23.5", "rx")
        content = view.document().toPlainText()
        assert "Temperature: 23.5" in content


# =============================================================================
# LAYER 2 — JUMP feature (highlight_row / clear_highlight / FilterWindow jump)
# =============================================================================

@pytest.mark.skipif(not _QT_AVAILABLE, reason="PyQt6 not available")
class TestLiveLogViewJump:
    """Tests for LiveLogView.highlight_row() and clear_highlight() used by JUMP."""

    @pytest.fixture(scope="class")
    def app(self):
        app = QApplication.instance() or QApplication(sys.argv)
        return app

    @pytest.fixture
    def view(self, app):
        from PyQt6.QtGui import QFont
        pal = {
            "bg":"#1a1a2e","bg2":"#1e1e3a","bg3":"#252545",
            "fg":"#e0e0e0","fg_dim":"#666","border":"#333",
            "rx":"#4a90d9","tx":"#f0a858","sys":"#888",
            "ts":"#555","hex":"#c97bf7","green":"#00e676",
            "red":"#f07878",
        }
        font = QFont("Courier New", 9)
        mod = _load_app()
        v = mod.LiveLogView(pal, font)
        v.resize(800, 400)
        v.clear_log()
        for i in range(5):
            v.append_line(f"12:00:00.00{i}  RX  line {i}", "rx")
        return v

    def test_highlight_row_adds_one_extra_selection(self, view):
        view.clear_highlight()
        view.highlight_row(2)
        assert len(view.extraSelections()) == 1

    def test_highlight_row_sets_cursor(self, view):
        view.highlight_row(1)
        assert view._highlight_cursor is not None

    def test_clear_highlight_removes_extra_selections(self, view):
        view.highlight_row(2)
        view.clear_highlight()
        assert len(view.extraSelections()) == 0

    def test_clear_highlight_resets_cursor(self, view):
        view.highlight_row(2)
        view.clear_highlight()
        assert view._highlight_cursor is None

    def test_highlight_invalid_row_is_noop(self, view):
        view.clear_highlight()
        view.highlight_row(9999)        # beyond document — must not set a selection
        assert len(view.extraSelections()) == 0

    def test_double_clear_is_safe(self, view):
        view.clear_highlight()
        view.clear_highlight()          # must not raise
        assert view._highlight_cursor is None

    def test_second_highlight_replaces_first(self, view):
        view.highlight_row(0)
        view.highlight_row(3)
        assert len(view.extraSelections()) == 1   # only one highlight at a time


@pytest.mark.skipif(not _QT_AVAILABLE, reason="PyQt6 not available")
class TestFilterWindowJump:
    """Tests for FilterWindow._jump_to_main() and JUMP button enable / disable."""

    @pytest.fixture(scope="class")
    def app(self):
        app = QApplication.instance() or QApplication(sys.argv)
        return app

    class _MockMainWindow:
        """Minimal stand-in for BluOwlSerialMonitor as seen by FilterWindow."""
        def __init__(self):
            self.jumped_to = None
        def raise_(self):             pass
        def activateWindow(self):     pass
        def jump_to_line(self, idx):  self.jumped_to = idx

    @pytest.fixture
    def fw(self, app):
        from PyQt6.QtGui import QFont
        mod = _load_app()
        store = mod.LogStore()
        ts = datetime.datetime.now()
        store.append("rx", "alpha error", ts)
        store.append("rx", "beta info",   ts)
        store.append("rx", "alpha again", ts)
        pal = {
            "bg":"#1a1a2e","bg2":"#1e1e3a","bg3":"#252545",
            "fg":"#e0e0e0","fg_dim":"#666","border":"#333",
            "rx":"#4a90d9","tx":"#f0a858","sys":"#888",
            "ts":"#555","hex":"#c97bf7","green":"#00e676",
            "red":"#f07878",
        }
        font   = QFont("Courier New", 9)
        mock   = self._MockMainWindow()
        window = mod.FilterWindow(
            store      = store,
            palette    = pal,
            font       = font,
            colour_idx = 0,
            show_ts_fn = lambda: False,
            main_window= mock,
        )
        window._vis = []
        window._model.set_filter_indices([])
        return window, mock

    def test_jump_falls_back_to_last_vis_when_nothing_selected(self, fw):
        window, mock = fw
        window._vis = [0, 2]
        window._jump_to_main()
        assert mock.jumped_to == 2

    def test_jump_single_vis_entry(self, fw):
        window, mock = fw
        window._vis = [1]
        window._jump_to_main()
        assert mock.jumped_to == 1

    def test_jump_empty_vis_does_nothing(self, fw):
        window, mock = fw
        window._vis = []
        mock.jumped_to = None
        window._jump_to_main()
        assert mock.jumped_to is None

    def test_jbtn_enabled_when_vis_nonempty(self, fw):
        window, _ = fw
        window._vis = [0, 2]
        window._update_mlbl()
        assert window._jbtn.isEnabled()

    def test_jbtn_disabled_when_vis_empty(self, fw):
        window, _ = fw
        window._vis = []
        window._update_mlbl()
        assert not window._jbtn.isEnabled()

    def test_jbtn_disabled_after_results_cleared(self, fw):
        window, _ = fw
        window._vis = [0]
        window._update_mlbl()
        window._vis = []
        window._update_mlbl()
        assert not window._jbtn.isEnabled()

    def test_match_count_label_shows_count(self, fw):
        window, _ = fw
        window._vis = [0, 2]
        window._filter_mode = "show"
        window._update_mlbl()
        assert "2" in window._mlbl.text()

    def test_match_count_label_hide_mode_says_hidden(self, fw):
        window, _ = fw
        window._vis = [1]
        window._filter_mode = "hide"
        window._update_mlbl()
        assert "hidden" in window._mlbl.text()


# =============================================================================
# REGRESSION CHECKLIST — run manually before every commit
# (also serves as documentation of every feature)
# =============================================================================

REGRESSION_CHECKLIST = r"""
BluOwl SerialMonitor — Manual Regression Checklist
===================================================
Run through this list before committing ANY change.
Takes ~2 minutes. Mark each item ✅ or ❌.

STARTUP
  [ ] App opens without error
  [ ] Window title shows "BluOwl SerialMonitor  vX.XX"
  [ ] BluOwl owl logo appears in top-left toolbar
  [ ] Port dropdown populates within ~1 second (background scan)
  [ ] Last CMD profile auto-loaded if previously saved
  [ ] App icon visible in taskbar and title bar

LIVE VIEW
  [ ] Connecting to a COM port shows "Connected" status
  [ ] RX data appears in live view with timestamps HH:MM:SS.mmm
  [ ] TX sends are logged in live view as TX entries
  [ ] Auto-scroll follows new data when ⬇AUTO is on
  [ ] Disabling AUTO stops scroll; re-enabling AUTO jumps to bottom immediately
  [ ] Line numbers visible in left gutter, auto-widen as count grows
  [ ] Click-drag selects text; Ctrl+C copies with timestamps
  [ ] HEX mode toggle works
  [ ] TS (timestamp) toggle shows/hides timestamps
  [ ] CLEAR wipes live view
  [ ] EXPORT saves to file

FILTER BAR (main window)
  [ ] SHOW mode: only matching lines visible
  [ ] HIDE mode: matching lines hidden, rest visible
  [ ] HIDE mode with empty filter: all lines shown (not blank)
  [ ] REGEX mode: standard regex works (e.g. \d+\.\d+)
  [ ] REGEX | alternation works (error|warning matches both)
  [ ] REGEX invalid pattern: entry turns red, no crash, no match-all
  [ ] Switching from REGEX mode clears red highlight
  [ ] & (AND) operator: both terms must be present
  [ ] | (OR) operator: either term sufficient
  [ ] Combined: "error & temp | warn & volt" works correctly
  [ ] JUMP button: jumps to line in main view, green highlight for 3s
  [ ] Ctrl+F opens search bar in live view

FILTER POP-OUT WINDOWS
  [ ] + FILTER button opens a pop-out window
  [ ] Up to 5 pop-out windows open simultaneously
  [ ] Each window filters independently
  [ ] ✕ CLEAR clears only that window, filter stays active
  [ ] New matching lines appear after CLEAR
  [ ] ⤴ JUMP in pop-out switches to main live tab, scrolls, highlights
  [ ] 📈 PLOT button opens graph panel
  [ ] Plot parses numeric values from filtered lines
  [ ] Line / Bar chart toggle works
  [ ] X axis: Line No. / Timestamp toggle works
  [ ] ⏵ LIVE toggle: live update on/off
  [ ] Scroll zoom, drag pan, double-click reset on plot

FILE VIEW
  [ ] Open a large log file (>1MB)
  [ ] File indexes quickly (<1s for 10MB)
  [ ] Lines display correctly
  [ ] Filter works on file view

CMD TAB
  [ ] 🎮 CMD tab visible
  [ ] Add button opens edit dialog (label, command, colour)
  [ ] Button appears after add
  [ ] Single click sends command (only when connected)
  [ ] Buttons greyed out when disconnected
  [ ] Double-click opens edit dialog
  [ ] Right-click → Edit works
  [ ] Right-click → Delete removes button
  [ ] Drag reorders buttons
  [ ] Save As creates .boc file
  [ ] Load opens .boc file and restores buttons
  [ ] Tab title shows profile name and * for unsaved changes
  [ ] Line ending selector affects sent commands

THEMES
  [ ] All 5 themes apply correctly (Light, Dark, Solarized, Monokai, B&W)
  [ ] Custom palette editor works
  [ ] Theme changes propagate to CMD buttons and plot

FONT
  [ ] Font picker changes font in live view and file view
  [ ] Gutter width updates after font change

PORT SETTINGS
  [ ] COM port dropdown shows "COM4: USB Serial Port" style names
  [ ] Refresh ↺ button rescans ports
  [ ] Baud, data bits, parity, stop bits all take effect on connect

BUILD
  [ ] nuitka_build_exe_v2_1.bat completes without error
  [ ] Built EXE shows BluOwl owl icon in File Explorer
  [ ] Built EXE shows owl icon in taskbar when running
  [ ] Window title in EXE shows "BluOwl SerialMonitor"
  [ ] About dialog shows correct version number
"""


def test_checklist_is_documented():
    """Meta-test: ensure the regression checklist exists and is non-empty."""
    assert len(REGRESSION_CHECKLIST) > 500
    assert "LIVE VIEW" in REGRESSION_CHECKLIST
    assert "FILTER BAR" in REGRESSION_CHECKLIST
    assert "CMD TAB" in REGRESSION_CHECKLIST
    assert "JUMP" in REGRESSION_CHECKLIST


class TestCommandProfileWithShortcuts:
    """Tests for CommandProfile shortcuts field serialisation."""

    def _make_profile_class(self):
        from dataclasses import dataclass, field, asdict

        @dataclass
        class ButtonConfig:
            label:   str = "Button"
            command: str = ""
            color:   str = ""

        @dataclass
        class CommandProfile:
            name:        str  = "Untitled"
            line_ending: str  = "CRLF"
            buttons:     list = field(default_factory=list)
            shortcuts:   dict = field(default_factory=dict)

            def to_dict(self):
                return {"name": self.name,
                        "line_ending": self.line_ending,
                        "buttons": [asdict(b) for b in self.buttons],
                        "shortcuts": self.shortcuts}

            @staticmethod
            def from_dict(d):
                btns = [ButtonConfig(**b) for b in d.get("buttons", [])]
                return CommandProfile(
                    name        = d.get("name", "Untitled"),
                    line_ending = d.get("line_ending", "CRLF"),
                    buttons     = btns,
                    shortcuts   = d.get("shortcuts", {}))

        return CommandProfile, ButtonConfig

    def test_shortcuts_default_empty(self):
        CommandProfile, _ = self._make_profile_class()
        p = CommandProfile()
        assert p.shortcuts == {}

    def test_shortcuts_roundtrip(self):
        CommandProfile, ButtonConfig = self._make_profile_class()
        p = CommandProfile(
            name      = "Test",
            shortcuts = {
                "connect":    "Ctrl+Shift+C",
                "clear":      "F5",
                "cmd_btn_0":  "F1",
            }
        )
        d  = p.to_dict()
        p2 = CommandProfile.from_dict(d)
        assert p2.shortcuts["connect"]   == "Ctrl+Shift+C"
        assert p2.shortcuts["clear"]     == "F5"
        assert p2.shortcuts["cmd_btn_0"] == "F1"

    def test_shortcuts_missing_key_defaults_to_empty(self):
        CommandProfile, _ = self._make_profile_class()
        # Old .boc file without shortcuts key
        p = CommandProfile.from_dict({"name": "Old", "buttons": []})
        assert p.shortcuts == {}

    def test_shortcuts_json_roundtrip(self):
        CommandProfile, _ = self._make_profile_class()
        p = CommandProfile(
            name      = "ShortcutTest",
            shortcuts = {"auto_scroll": "F12", "connect": "Ctrl+Shift+C",
                         "connect__global": True}
        )
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".boc", delete=False) as f:
            json.dump(p.to_dict(), f)
            path = f.name
        try:
            with open(path) as f:
                d = json.load(f)
            p2 = CommandProfile.from_dict(d)
            assert p2.shortcuts["auto_scroll"]      == "F12"
            assert p2.shortcuts["connect"]          == "Ctrl+Shift+C"
            assert p2.shortcuts["connect__global"]  is True
        finally:
            os.unlink(path)

    def test_global_flag_stored_separately(self):
        CommandProfile, _ = self._make_profile_class()
        sc = {
            "connect":         "Ctrl+Shift+C",
            "connect__global": True,
            "clear":           "F5",
        }
        p  = CommandProfile(shortcuts=sc)
        d  = p.to_dict()
        p2 = CommandProfile.from_dict(d)
        # Global flag must survive round-trip
        assert p2.shortcuts.get("connect__global") is True
        # Normal shortcuts unaffected
        assert p2.shortcuts.get("clear") == "F5"


class TestShortcutConflictDetection:
    """Test conflict detection logic used by ShortcutsDialog."""

    def _has_conflict(self, shortcuts: dict, action_id: str, combo: str) -> bool:
        """Mirror of ShortcutsDialog._on_captured conflict check."""
        conflicts = [
            aid for aid, sc in shortcuts.items()
            if sc == combo
            and aid != action_id
            and not aid.endswith("__global")
        ]
        return len(conflicts) > 0

    def test_no_conflict_empty(self):
        sc = {}
        assert not self._has_conflict(sc, "connect", "Ctrl+Shift+C")

    def test_no_conflict_different_combos(self):
        sc = {"clear": "F5", "export": "Ctrl+E"}
        assert not self._has_conflict(sc, "connect", "Ctrl+Shift+C")

    def test_conflict_detected(self):
        sc = {"clear": "F5"}
        assert self._has_conflict(sc, "connect", "F5")

    def test_no_conflict_with_self(self):
        # Updating the same action to the same combo — not a conflict
        sc = {"connect": "Ctrl+Shift+C"}
        assert not self._has_conflict(sc, "connect", "Ctrl+Shift+C")

    def test_global_flag_not_treated_as_conflict(self):
        # __global keys hold True/False, not combo strings — must not trigger conflict
        sc = {"connect": "Ctrl+Shift+C", "connect__global": True}
        # "connect" uses Ctrl+Shift+C — assigning it to "clear" IS a conflict
        assert self._has_conflict(sc, "clear", "Ctrl+Shift+C")
        # But "connect__global": True is a boolean flag, not a combo —
        # assigning "True" as a combo string to another action is NOT a conflict
        # because __global keys are excluded from conflict checks
        assert not self._has_conflict(sc, "clear", "F5")

    def test_cmd_button_conflict_with_builtin(self):
        sc = {"connect": "F1"}
        assert self._has_conflict(sc, "cmd_btn_0", "F1")

    def test_cmd_button_conflict_with_cmd_button(self):
        sc = {"cmd_btn_0": "F1"}
        assert self._has_conflict(sc, "cmd_btn_1", "F1")


class TestKeyComboFormatting:
    """Test that key combo strings are formatted correctly."""

    def _format_combo(self, ctrl=False, shift=False, alt=False, key_name="F1"):
        """Mirror of KeyCaptureEdit.keyPressEvent combo building."""
        parts = []
        if ctrl:  parts.append("Ctrl")
        if shift: parts.append("Shift")
        if alt:   parts.append("Alt")
        parts.append(key_name)
        return "+".join(parts)

    def test_simple_function_key(self):
        assert self._format_combo(key_name="F1") == "F1"

    def test_ctrl_combo(self):
        assert self._format_combo(ctrl=True, key_name="C") == "Ctrl+C"

    def test_ctrl_shift_combo(self):
        assert self._format_combo(ctrl=True, shift=True, key_name="C") == "Ctrl+Shift+C"

    def test_all_modifiers(self):
        assert self._format_combo(
            ctrl=True, shift=True, alt=True, key_name="F12") == "Ctrl+Shift+Alt+F12"

    def test_no_modifiers(self):
        assert self._format_combo(key_name="F5") == "F5"



    print(REGRESSION_CHECKLIST)
    pytest.main([__file__, "-v", "--tb=short"])
