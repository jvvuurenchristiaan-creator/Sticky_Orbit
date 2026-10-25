"""The always-on-top launcher orb that lives in the top-right corner."""
import time

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter
from PySide6.QtWidgets import QWidget

from .gfx import draw_orb

START = time.perf_counter()


def anim_time():
    """Shared clock so the orb and the wheel's mini-orb pulse in sync."""
    return time.perf_counter() - START


class OrbWidget(QWidget):
    activated = Signal()
    context_requested = Signal(QPoint)

    SIZE = 104
    R = 19

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("")
        self.hover = 0.0
        self.inside = False
        self.armed = True
        self.type_counts = {}
        self.total = 0

        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        self.hover_timer = QTimer(self)
        self.hover_timer.setSingleShot(True)
        self.hover_timer.setInterval(140)
        self.hover_timer.timeout.connect(self._fire)

        # Other apps occasionally claim topmost; politely reclaim it.
        self.raise_timer = QTimer(self)
        self.raise_timer.timeout.connect(lambda: self.isVisible() and self.raise_())
        self.raise_timer.start(2500)

    def center_global(self):
        return self.mapToGlobal(QPoint(self.SIZE // 2, self.SIZE // 2))

    def place(self, screen):
        avail = screen.availableGeometry()
        self.move(avail.right() - self.SIZE + 1, avail.top())

    def set_notes(self, notes):
        counts = {}
        for n in notes:
            counts[n.type] = counts.get(n.type, 0) + 1
        self.type_counts, self.total = counts, len(notes)
        self.update()

    def show_orb(self):
        # Don't re-trigger instantly if the cursor is still parked on the orb.
        self.armed = not self.geometry().contains(QCursor.pos())
        self.inside = not self.armed
        self.hover = 0.0
        self.show()
        self.raise_()
        self.clock.restart()
        self.timer.start(16)

    def hide_orb(self):
        self.hover_timer.stop()
        self.timer.stop()
        self.hide()

    def enterEvent(self, e):
        self.inside = True
        if self.armed:
            self.hover_timer.start()

    def leaveEvent(self, e):
        self.inside = False
        self.armed = True
        self.hover_timer.stop()

    def _fire(self):
        if self.inside:
            self.activated.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.activated.emit()
        elif e.button() == Qt.RightButton:
            self.context_requested.emit(e.globalPosition().toPoint())

    def _tick(self):
        dt = min(0.05, self.clock.restart() / 1000.0)
        target = 1.0 if self.inside else 0.0
        self.hover += (target - self.hover) * min(1.0, dt * 10)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        c = QPointF(self.SIZE / 2, self.SIZE / 2)
        draw_orb(p, c, self.R * (1 + 0.12 * self.hover), anim_time(), self.type_counts, self.total, self.hover)
