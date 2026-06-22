# CLAUDE.md — BluOwl SerialMonitor

Machine instructions for Claude Code. Read this file completely before doing anything.

---

## Project identity

| Field | Value |
|---|---|
| App name | BluOwl SerialMonitor |
| Team | Thvaraa |
| Current version | 5.18 |
| Main script | `BluOwl_SerialMonitor_V_5.18.py` |
| Build script | `nuitka_build_exe_v2_1.bat` |
| Test file | `tests/test_bluowl.py` |
| Profile files | `*.boc` (BluOwl Command — plain JSON) |
| Settings file | `~/.BluOwlSerialMonitor_settings.json` |
| GitHub | https://github.com/thvaraa-vishnu/BluOwl-SerialMonitor |

---

## ⚠ Three-confirmation protocol for git commands

**Never run any git command without three explicit confirmations from the user.**

Before any `git add`, `git commit`, `git push`, `git rebase`, `git reset`, or `git merge`:

1. **Show** exactly what will be staged/committed/pushed
2. **Ask** "Shall I proceed?" — wait for YES
3. **Confirm** the specific command — wait for YES again
4. **Run** — then show the output and ask "Does this look correct?" before continuing

This applies even if the user says "just do it" or "go ahead". The protocol is non-negotiable.

---

## Versioning rules

- Version format: `X.Y` (e.g. `5.18`, `5.19`)
- `APP_VERSION` is on line ~74 of the main script
- Every meaningful change bumps the version
- File must be renamed to match: `BluOwl_SerialMonitor_V_X.Y.py`
- Changelog entry added at the top of the `CHANGELOG` string
- Bat file version is independent (e.g. `v2.1`) — bump only when bat changes
- Bat filename must match its internal version: `nuitka_build_exe_vX_Y.bat`

---

## Architecture

### Main window
`BluOwlSerialMonitor(QMainWindow)` — single instance, owns everything.

### Data layer
| Class | Purpose |
|---|---|
| `LogStore` | Piece-table bytearray — stores all RX/TX/SYS entries. Thread-safe. O(1) append and retrieval. Timestamps in milliseconds via `time.perf_counter()`. |
| `MmapFileStore` | mmap-backed store for File View. numpy-accelerated line indexing. |

### UI layer
| Class | Purpose |
|---|---|
| `LiveLogView(QPlainTextEdit)` | Live log display. Character-selectable. Has `_LineGutter` for line numbers. |
| `LogView(QListView)` | File view only — virtual rendering via `LogDelegate`. |
| `FilterWindow(QMainWindow)` | Pop-out filter window. Up to 5 simultaneously. Has CLEAR button, JUMP, PLOT panel. |
| `CommandPanel(QWidget)` | CMD tab — renameable buttons, drag-to-reorder, profile load/save. |
| `PlotView(QWidget)` | Pure QPainter signal plotter inside filter pop-outs. |

### Shortcut system
| Class | Purpose |
|---|---|
| `KeyCaptureEdit(QLineEdit)` | Click → press key combo → recorded as string. |
| `ShortcutsDialog(QDialog)` | Edit → Shortcuts… dialog. Conflict detection. Global flag per shortcut. |
| `ShortcutManager` | Registers/unregisters `QShortcut` objects. Re-applies on profile load. |

### Workers (QThread)
| Class | Purpose |
|---|---|
| `RxWorker` | Serial read loop. Emits `data_ready(bytes)`. |
| `LogFilterWorker` | Off-thread filter scan for live view. |
| `FileIndexWorker` | Off-thread mmap indexing for file view. |
| `FileFilterWorker` | Off-thread filter scan for file view. |

### CMD system
| Class | Purpose |
|---|---|
| `ButtonConfig` | Dataclass: label, command, color. |
| `CommandProfile` | Dataclass: name, line_ending, buttons[], shortcuts{}. Serialises to/from `.boc` JSON. |
| `CmdButton(QPushButton)` | Single command button. Click=send, double-click=edit, right-click=menu, drag=reorder. |
| `FlowLayout(QLayout)` | Wrapping left-to-right layout with drag-drop reorder support. |

---

## Key constants

```python
APP_VERSION     = "5.18"
FLUSH_MS        = 50          # RX buffer drain interval
DEFAULT_FONT    = "Courier New"
DEFAULT_FONT_SZ = 10
MAX_FILTER_WINDOWS = 5
LINE_ENDINGS    = {"None":b"", "CR":b"\r", "LF":b"\n", "CRLF":b"\r\n"}
```

---

## Built-in shortcut action IDs

```python
BUILTIN_ACTIONS = [
    ("connect",           "Connect / Disconnect"),
    ("clear",             "Clear live view"),
    ("export",            "Export log"),
    ("auto_scroll",       "Toggle auto-scroll"),
    ("filter_focus",      "Focus filter bar"),
    ("new_filter_window", "Open new filter window"),
    ("switch_live",       "Switch to LIVE tab"),
    ("switch_file",       "Switch to FILE VIEW tab"),
    ("switch_cmd",        "Switch to CMD tab"),
    ("timestamp_toggle",  "Toggle timestamps"),
    ("hex_toggle",        "Toggle HEX mode"),
]
```
To add a new built-in action: add entry to `BUILTIN_ACTIONS` AND add the callback to the `ShortcutManager` init dict in `BluOwlSerialMonitor.__init__`.

---

## PyQt6 import rules

`QAction` is in `PyQt6.QtGui` — NOT `QtWidgets`. This is a common PyQt6 mistake.

```python
from PyQt6.QtGui import QAction       # ✅ correct
from PyQt6.QtWidgets import QAction   # ❌ ImportError
```

All imports are at the top of the file in three blocks:
- `PyQt6.QtWidgets` — all widget classes
- `PyQt6.QtCore` — Qt, signals, timers, model classes
- `PyQt6.QtGui` — fonts, colours, painters, QAction, QDrag, QShortcut

---

## Filter logic

`eval_filter(text, filt, mode)` — three modes:

| Mode | Logic |
|---|---|
| `show` | `\|` = OR groups, `&` = AND within group. Case-insensitive substring match. |
| `hide` | Same logic — returns True for lines that MATCH (caller hides them). Empty filter = show all (hide nothing). |
| `regex` | Uses `regex` module (PCRE) if installed, falls back to stdlib `re`. Invalid regex returns `False` (not `True`). |

---

## Threading rules

- **UI updates must happen on the main thread only.** Use `pyqtSignal` to post results back from workers.
- `LogStore` is thread-safe (internal `threading.Lock`).
- `_refresh_ports()` runs in a background thread — posts results via `_ports_ready` signal.
- `RxWorker` emits `data_ready` → connected to `_rx_sig` → UI thread processes via `_on_rx_data`.
- Never call `QWidget` methods from a non-UI thread.

---

## Timestamp precision

- `LogStore` stores `ts_ms` (milliseconds since session epoch) as `uint32`.
- Capture uses `time.perf_counter()` anchored to `datetime.datetime.now()` at init — sub-millisecond accuracy on Windows.
- Display format: `HH:MM:SS.mmm` (12 chars via `strftime("%H:%M:%S.%f")[:12]`).
- `datetime.now()` alone has ~15ms resolution on Windows — do NOT use it for timestamp capture.

---

## Testing

```cmd
pip install pytest
pytest tests/test_bluowl.py -v
```

**All tests must pass before committing any change.**

Test layers:
- **Layer 1** — Pure logic (no Qt): `eval_filter`, `LogStore`, `CommandProfile`, helpers, shortcuts
- **Layer 2** — Qt widgets (headless): `LiveLogView`, gutter, append

**When adding a feature:**
1. Run tests → all green
2. Write test(s) for the new feature
3. Implement the feature
4. Run tests → all green
5. Commit

Test file location: `tests/test_bluowl.py`

---

## `.boc` profile file format

```json
{
  "name": "Helmet Test Suite",
  "line_ending": "CRLF",
  "buttons": [
    {"label": "Power On",  "command": "PWR_ON",  "color": "#2a5a2a"},
    {"label": "BT Scan",   "command": "BT_SCAN", "color": ""}
  ],
  "shortcuts": {
    "connect":          "Ctrl+Shift+C",
    "connect__global":  true,
    "cmd_btn_0":        "F1",
    "cmd_btn_1":        "F2"
  }
}
```

`__global` suffix keys are boolean flags — not shortcut combos. They opt the shortcut into `ApplicationShortcut` context (fires even when text field has focus).

Old `.boc` files without `shortcuts` key load correctly (defaults to `{}`).

---

## Build (Nuitka)

```cmd
nuitka_build_exe_v2_1.bat
```

Key flags:
- `--onefile` — single EXE
- `--disable-cache=all` — always recompile from current `.py`
- `--onefile-tempdir-spec="{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}"` — version-specific cache
- `--enable-plugin=pyqt6`
- `--include-package=serial,numpy,regex`
- Nukes all previous caches before building

Output: `BluOwl_SerialMonitor_V_X.Y.exe` in both `dist\` and the project root.

---

## File structure

```
BluOwl-SerialMonitor/
├── BluOwl_SerialMonitor_V_5.18.py   ← main source (rename on version bump)
├── nuitka_build_exe_v2_1.bat        ← build script
├── README.md
├── CLAUDE.md                        ← this file
├── .gitignore                       ← excludes *.exe, dist/, __pycache__, etc.
└── tests/
    └── test_bluowl.py               ← pytest test suite
```

---

## Regression checklist

Before every commit, run through the manual checklist at the bottom of `tests/test_bluowl.py` (print it with `python tests/test_bluowl.py`). Takes ~2 minutes.

Key areas to always verify after any change:
- JUMP button works in main window and filter pop-outs
- Line numbers visible in live view gutter
- Auto-scroll re-enables immediately on toggle
- Filter SHOW/HIDE/REGEX all produce correct results
- HIDE + empty filter shows all lines (not blank)
- CMD tab buttons send correctly and are greyed when disconnected
- Shortcuts dialog shows correct friendly labels (not raw action IDs)
- Shortcuts fire correctly after profile load

---

## Common mistakes to avoid

| Mistake | Correct approach |
|---|---|
| `QAction` from `QtWidgets` | Import from `QtGui` |
| `datetime.now()` for timestamps | Use `self._store._now_hires()` |
| Direct byte offset on struct data | Use `REC.unpack_from()` for all field access |
| Updating UI from worker thread | Emit a signal, handle in main thread |
| `except: return True` in filter | `except re.error: return False` |
| Adding method body to wrong method | Check indentation and method boundaries carefully |
| Not bumping version on change | Always bump `APP_VERSION` and rename file |
| Committing without running tests | Run `pytest tests/test_bluowl.py -v` first |
