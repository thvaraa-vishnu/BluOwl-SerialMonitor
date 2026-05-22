# BluOwl SerialMonitor

A fast, feature-rich serial port (UART) monitor and logger for Windows — built with Python and PyQt6.

> Made by **Team Thvaraa**

---

## Features

- **Live serial logging** — RX/TX display with timestamps, HEX mode, and auto-scroll
- **File logging** — automatically saves logs to timestamped files on connect
- **Advanced filtering** — SHOW / HIDE / REGEX modes with `&` (AND) and `|` (OR) operators
- **Filter pop-out windows** — up to 5 independent filtered views simultaneously, each with a JUMP button back to the main view
- **Signal plotter** — built into each filter window; auto-parses numeric values from log lines and plots them as line or bar charts with live update, zoom, pan, and hover tooltips
- **File viewer** — open and browse large log files (60MB+ files index in ~0.2s using numpy)
- **Text selection** — character-level text selection and Ctrl+C copy in the live view (including timestamps)
- **Tera Term style port names** — COM port dropdown shows full device description (e.g. `COM4: USB Serial Port`)
- **Themes** — 5 built-in colour themes (Light, Dark, Solarized, Monokai, B&W) + custom palette editor
- **Font picker**, HEX display, timestamp toggle, line count display
- **Fast startup** — COM port scan runs in background thread; window appears immediately

---

## Requirements

- Windows 10 / 11
- Python 3.11+
- Dependencies:

```
pip install pyserial PyQt6 numpy
```

---

## Running from Source

```cmd
python bluowl_serialmonitor.py
```

---

## Building the EXE

Use the included `nuitka_build_exe_v1_3.bat`:

1. Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with **Desktop development with C++**
2. Install Nuitka:
   ```cmd
   pip install nuitka
   ```
3. Place the `.bat` and `.py` in the same folder
4. Double-click `nuitka_build_exe_v1_3.bat`
5. The EXE will appear in the `dist\` folder

> **Note:** First launch after building extracts files to a local cache (`%LOCALAPPDATA%\BluOwl SerialMonitor\`). Every subsequent launch is fast.

---

## Download

Pre-built EXE available on the [Releases](../../releases) page — no installation needed, just double-click and run.

---

## Usage

1. Select your COM port from the dropdown (shows full device name)
2. Set baud rate, data bits, parity, stop bits
3. Click **Connect**
4. Use the filter bar to show/hide specific lines
5. Click **+ Filter Window** to open a filtered pop-out view
6. Click **📈 PLOT** in any filter window to visualise numeric data

---

## Screenshots

*Coming soon*

---

## Changelog

See the **About** dialog inside the app (Help → About) for the full version history.

---

## License

MIT License — free to use, modify, and distribute.

---

*BluOwl SerialMonitor is an open-source project by Team Thvaraa.*
