<div align="center">

<img src="docs/orb.png" width="104" alt="Sticky Orb launcher" />

# Sticky Orb

**A sticky-note desktop app for Windows, written in pure Python.**

A glowing orb waits in the corner of your screen. Hover over it and it opens into a spinning wheel of colour-coded sticky notes. Every note is a plain Markdown file.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![PySide6](https://img.shields.io/badge/Qt-PySide6-41CD52?logo=qt&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Windows-0078D4?logo=windows&logoColor=white)
![Storage](https://img.shields.io/badge/storage-Markdown-000000?logo=markdown&logoColor=white)

<img src="docs/wheel.png" width="640" alt="The Sticky Orb note wheel" />

</div>

---

## ✨ Highlights

- **Out of the way until you need it.** A small animated orb sits always-on-top in the top-right corner. Hover over it and the wheel opens; move the mouse away and it closes.
- **A wheel you can spin.** Notes are laid out around a ring. Scroll, drag (it springs into place) or use the arrow keys. The focused note is enlarged, and its full contents show in the glass hub in the middle.
- **Colour-coded note types.** Every type has its own gradient, and the wheel's colours follow whichever note is in focus.

  | To Do | Task | Project | Follow Up | Email |
  |:---:|:---:|:---:|:---:|:---:|
  | 🟧 amber | 🟦 blue | 🟪 violet | 🩷 pink | 🟩 green |

- **Plain Markdown files.** Every note is a readable `.md` file with YAML front matter. Edit the files in VS Code or Obsidian, or keep them in git; the app picks up your changes.
- **Archive, don't delete.** Clicking **×** moves the note into a weekly archive folder. **Undo** brings it straight back.
- **Moves with its folder.** `notes/` and `archive/` are found relative to the app, so the whole folder can be copied, synced or moved anywhere.
- **Python source or a single EXE.** Run it from Python, or build one `StickyOrb.exe` that needs nothing installed.
- **Visual effects drawn in code.** Particle bursts, orbiting stars, drifting coloured mist, light sweeping across cards, spring physics and staggered entrance animations. Everything is painted with QPainter; there are no image assets.

<div align="center">
<img src="docs/editor.png" width="520" alt="The note editor" />
</div>

## 🚀 Getting started

### Option 1: run the EXE

Double-click **`StickyOrb.exe`**. Look for the orb in the top-right corner of your screen.

### Option 2: run from source

```bash
git clone <your-repo-url> Sticky
cd Sticky
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw StickyOrb.pyw
```

Or just double-click **`Start Sticky Orb.bat`**. The first time, it creates the virtual environment for you.

> Requires Python 3.10+ and PySide6.

## 🎮 Using it

| Action | How |
|---|---|
| Open the wheel | Hover over the orb (or click the tray icon) |
| Spin | Mouse wheel, drag around the ring, or `←` `→` |
| Focus a note | Click it |
| Edit | Click the focused note again, double-click any note, or `Enter` |
| New note | **+** in the hub, or `N` |
| Archive | Hover over a card and click **×** in its top-right corner (or press `Delete`) |
| Undo archive | **Undo** at the bottom of the wheel, or `Ctrl+Z` (shown for 6 s) |
| Filter by type | Pills along the bottom edge, or `0` (all) to `5` |
| Save / cancel in the editor | `Ctrl+Enter` / `Esc` |
| Close the wheel | Move the mouse away, press `Esc`, or click the orb |
| Menu | Right-click the orb, the wheel or the tray icon |

## 🗂️ How notes are stored

```
Sticky/
├── notes/                                   ← notes on the board
│   └── plan-the-week-821fffbd.md
└── archive/                                 ← notes closed with ×, grouped by ISO week
    └── 2026-W43 (19 Oct - 25 Oct 2026)/
        └── reply-to-the-design-review-thread-580f8020.md
```

Each note is a standard Markdown file:

```markdown
---
id: 821fffbd
title: Plan the week
type: todo
created: 2026-10-25T14:22:48
updated: 2026-10-25T14:22:48
---

# Plan the week

- [ ] Clear the inbox
- [x] Book flights
- [ ] Prepare the demo
```

- Archived notes also get an `archived:` timestamp.
- You can drop any `.md` file into `notes/` and it shows up on the board the next time the wheel opens. Files without front matter are fine: the title comes from the first `# heading`.
- `type` accepts `todo`, `task`, `project`, `followup` or `email`. Readable forms like `Follow Up` or `Tasks` also work.
- Set the environment variable `STICKY_NOTES_DIR` to keep notes somewhere else.

## 📦 Building the EXE

```bash
build_exe.bat
```

The script installs PyInstaller into `.venv`, renders the orb icon, and writes a single-file **`StickyOrb.exe`** into the project folder. The Python source is left untouched, so rebuild whenever you change the code. The EXE and the Python version share the same `notes/` and `archive/` folders. Only one copy runs at a time: starting a second copy just opens the wheel in the first.

## 🏁 Start with Windows

Press `Win + R`, type `shell:startup`, and put a shortcut to `StickyOrb.exe` (or `Start Sticky Orb.bat`) in that folder.

## 🧱 Project structure

```
stickyorb/
├── app.py      # starts the app: orb, wheel, tray icon, single-instance check, paths
├── orb.py      # the always-on-top launcher orb
├── wheel.py    # the note wheel: layout, spring physics, particles, input
├── editor.py   # glass editor panel with the type picker
├── gfx.py      # painting helpers: cards, orb, text wrapping, Markdown preview
├── store.py    # Markdown storage, weekly archive, first-run sample notes
└── theme.py    # colours, fonts, easing
StickyOrb.pyw   # entry point
build_exe.bat   # PyInstaller build
```

## 🎨 Customising

- **Colours, icons and labels** for each type live in `NOTE_TYPES` in [`stickyorb/theme.py`](stickyorb/theme.py).
- **Wheel geometry** (ring radius, hub size, how many notes before the ring scrolls) is set by the constants at the top of [`stickyorb/wheel.py`](stickyorb/wheel.py).
- **Orb position** is set in `OrbWidget.place()` in [`stickyorb/orb.py`](stickyorb/orb.py).

## 🛠️ Built with

- [Python](https://www.python.org/)
- [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/): translucent frameless windows, QPainter rendering, animation
- [PyInstaller](https://pyinstaller.org/): single-file Windows executable
