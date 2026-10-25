"""Wires the orb, the wheel, the tray icon and storage together."""
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .gfx import draw_orb
from .orb import OrbWidget, anim_time
from .store import NoteStore, seed_examples
from .wheel import WheelWindow

APP_KEY = "StickyOrb-single-instance"
MENU_STYLE = """
QMenu { background: #14162b; color: #e8ebff; border: 1px solid #2c3060; padding: 6px; }
QMenu::item { padding: 7px 22px; border-radius: 6px; }
QMenu::item:selected { background: #2f3680; }
QMenu::separator { height: 1px; background: #2c3060; margin: 5px 8px; }
"""


def base_dir():
    """The solution folder: next to StickyOrb.exe when frozen, else the project root.
    Everything is resolved from here, so the whole folder can be moved anywhere."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def notes_dir():
    env = os.environ.get("STICKY_NOTES_DIR")
    return Path(env) if env else base_dir() / "notes"


def archive_dir():
    return base_dir() / "archive"


def orb_icon():
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    draw_orb(p, QPointF(32, 32), 15, 1.0, {}, 0, glyph="✦")
    p.end()
    return QIcon(pm)


class Controller:
    def __init__(self, app):
        self.app = app
        self.store = NoteStore(notes_dir(), archive_dir())
        seed_examples(self.store)

        self.wheel = WheelWindow(self.store)
        self.orb = OrbWidget()
        self.orb.set_notes(self.wheel.notes)
        self._closed_at = 0.0

        self.orb.activated.connect(self.open_wheel)
        self.orb.context_requested.connect(self.show_menu)
        self.wheel.context_requested.connect(self.show_menu)
        self.wheel.closed.connect(self._on_wheel_closed)
        self.wheel.notes_changed.connect(self.orb.set_notes)

        self.menu = QMenu()
        self.menu.setStyleSheet(MENU_STYLE)
        for text, slot in (("Open the wheel", lambda: self.open_wheel(force=True)),
                           ("New note", self.new_note), (None, None),
                           ("Open notes folder", self.open_folder),
                           ("Open archive folder", self.open_archive), (None, None),
                           ("Quit Sticky Orb", app.quit)):
            if text is None:
                self.menu.addSeparator()
            else:
                action = QAction(text, self.menu)
                action.triggered.connect(slot)
                self.menu.addAction(action)

        self.tray = QSystemTrayIcon(orb_icon(), app)
        self.tray.setToolTip("Sticky Orb")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(
            lambda reason: reason == QSystemTrayIcon.Trigger and self.open_wheel(force=True))
        self.tray.show()

        screen = QGuiApplication.primaryScreen()
        self.orb.place(screen)
        screen.availableGeometryChanged.connect(lambda *_: self.orb.place(screen))
        self.orb.show_orb()

    def open_wheel(self, force=False):
        if self.wheel.isVisible() and self.wheel.opening:
            return
        if not force and time.monotonic() - self._closed_at < 0.35:
            return
        self.orb.hide_orb()
        self.wheel.show_wheel(self.orb.center_global())

    def _on_wheel_closed(self):
        self._closed_at = time.monotonic()
        self.orb.show_orb()

    def new_note(self):
        self.open_wheel(force=True)
        QTimer.singleShot(300, self.wheel.new_note)

    def open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.folder)))

    def open_archive(self):
        self.store.archive_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.archive_folder)))

    def show_menu(self, pos):
        self.menu.popup(pos)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Sticky Orb")
    app.setQuitOnLastWindowClosed(False)

    probe = QLocalSocket()
    probe.connectToServer(APP_KEY)
    if probe.waitForConnected(250):          # already running: just pop the wheel open there
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(250)
        return 0

    QLocalServer.removeServer(APP_KEY)
    server = QLocalServer()
    server.listen(APP_KEY)
    ctrl = Controller(app)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), ctrl.open_wheel(force=True)))
    app.setWindowIcon(orb_icon())
    return app.exec()
