"""Glass editor panel for creating and editing a note."""
from PySide6.QtCore import (QEasingCurve, QParallelAnimationGroup, QPoint, QPointF, QPropertyAnimation, QRectF,
                            QSize, Qt, Signal)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPalette,
                           QPen, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from .theme import NOTE_TYPES, TYPE_ORDER, family, font, type_colors, with_alpha


class TypeChip(QAbstractButton):
    def __init__(self, key, parent):
        super().__init__(parent)
        self.key = key
        info = NOTE_TYPES[key]
        self.setText(f"{info['icon']}  {info['label']}")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._font = font(12, QFont.DemiBold)

    def sizeHint(self):
        return QSize(QFontMetrics(self._font).horizontalAdvance(self.text()) + 26, 32)

    def minimumSizeHint(self):
        return QSize(QFontMetrics(self._font).horizontalAdvance(self.text()) + 14, 32)

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        c1, c2 = type_colors(self.key)
        rad = r.height() / 2
        if self.isChecked():
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r, rad, rad)
            p.setPen(QColor(255, 255, 255))
        else:
            hov = self.underMouse()
            p.setPen(QPen(with_alpha(c1, 170 if hov else 90), 1.2))
            p.setBrush(QColor(255, 255, 255, 24 if hov else 10))
            p.drawRoundedRect(r, rad, rad)
            p.setPen(c1.lighter(115))
        p.setFont(self._font)
        p.drawText(r, Qt.AlignCenter, self.text())


class EditorPanel(QWidget):
    saved = Signal(object, str, str, str)   # note-or-None, title, type, content
    closed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.note = None
        self.current_type = "todo"
        self._anim = None
        self.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 26)
        root.setSpacing(14)

        self.heading = QLabel("NEW NOTE", objectName="heading")
        root.addWidget(self.heading)

        self.title_edit = QLineEdit(placeholderText="Header…")
        self.title_edit.setMaxLength(140)
        root.addWidget(self.title_edit)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.chips = {}
        for key in TYPE_ORDER:
            chip = TypeChip(key, self)
            self.group.addButton(chip)
            chips.addWidget(chip)
            self.chips[key] = chip
            chip.clicked.connect(lambda _=False, k=key: self._set_type(k))
        root.addLayout(chips)

        self.body_edit = QPlainTextEdit(placeholderText="Contents…  (Markdown welcome: - [ ] checklists, **bold**, lists)")
        self.body_edit.setTabChangesFocus(True)
        root.addWidget(self.body_edit, 1)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        hint = QLabel("Ctrl+Enter to save  ·  Esc to cancel", objectName="hint")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self.cancel_btn = QPushButton("Cancel", objectName="cancel", cursor=Qt.PointingHandCursor)
        self.save_btn = QPushButton("Save note", objectName="save", cursor=Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.cancel)
        self.save_btn.clicked.connect(self._save)
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.save_btn)
        root.addLayout(bottom)

        for edit in (self.title_edit, self.body_edit):
            pal = edit.palette()
            pal.setColor(QPalette.PlaceholderText, QColor(220, 225, 255, 95))
            edit.setPalette(pal)

        for seq in ("Ctrl+Return", "Ctrl+Enter", "Ctrl+S"):
            QShortcut(QKeySequence(seq), self, self._save)
        QShortcut(QKeySequence(Qt.Key_Escape), self, self.cancel)
        self.title_edit.returnPressed.connect(self.body_edit.setFocus)

        self._apply_theme()

    # ── public API ──────────────────────────────────────────────────────────
    def open_for(self, note=None, default_type="todo"):
        self.note = note
        self.heading.setText("EDIT NOTE" if note else "NEW NOTE")
        self.title_edit.setText(note.title if note else "")
        self.body_edit.setPlainText(note.content if note else "")
        self._set_type(note.type if note else default_type)
        self._animate(True)
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def cancel(self):
        if self.isVisible():
            self._animate(False)

    # ── internals ───────────────────────────────────────────────────────────
    def _set_type(self, key):
        self.current_type = key
        self.chips[key].setChecked(True)
        self._apply_theme()
        self.update()

    def _save(self):
        if not self.isVisible():
            return
        title = self.title_edit.text().strip() or "Untitled"
        self.saved.emit(self.note, title, self.current_type, self.body_edit.toPlainText())
        self._animate(False)

    def _animate(self, show):
        if self._anim:
            self._anim.stop()
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        home = self.pos() if not show else self._home()
        if show:
            self.move(home)
            self.show()
            self.raise_()
        fade = QPropertyAnimation(effect, b"opacity", self)
        fade.setDuration(260 if show else 180)
        fade.setStartValue(0.0 if show else 1.0)
        fade.setEndValue(1.0 if show else 0.0)
        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(fade.duration())
        slide.setStartValue(home + QPoint(0, 22) if show else home)
        slide.setEndValue(home if show else home + QPoint(0, 14))
        curve = QEasingCurve.OutCubic if show else QEasingCurve.InCubic
        fade.setEasingCurve(curve)
        slide.setEasingCurve(curve)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(slide)

        def done():
            self.setGraphicsEffect(None)   # keep text crisp once settled
            if not show:
                self.hide()
                self.move(home)
                self.closed.emit()

        group.finished.connect(done)
        self._anim = group
        group.start()

    def _home(self):
        parent = self.parentWidget()
        return QPoint((parent.width() - self.width()) // 2, (parent.height() - self.height()) // 2)

    def _apply_theme(self):
        info = NOTE_TYPES[self.current_type]
        c1, c2, fam = info["c1"], info["c2"], family()
        self.setStyleSheet(f"""
            * {{ font-family: '{fam}'; }}
            QLabel#heading {{ color: {c1}; font-size: 11px; font-weight: 700; letter-spacing: 3px; }}
            QLabel#hint {{ color: rgba(220,225,255,110); font-size: 11px; }}
            QLineEdit {{
                background: rgba(255,255,255,12); border: 1px solid rgba(255,255,255,32);
                border-radius: 12px; padding: 10px 14px; color: #F4F6FF;
                font-size: 19px; font-weight: 600; selection-background-color: {c2};
            }}
            QLineEdit:focus {{ border: 1px solid {c1}; background: rgba(255,255,255,18); }}
            QPlainTextEdit {{
                background: rgba(255,255,255,10); border: 1px solid rgba(255,255,255,28);
                border-radius: 12px; padding: 8px 10px; color: #E6E9FF;
                font-size: 14px; selection-background-color: {c2};
            }}
            QPlainTextEdit:focus {{ border: 1px solid {c1}; }}
            QPushButton {{ border-radius: 17px; padding: 8px 20px; font-size: 13px; font-weight: 600; min-height: 18px; }}
            QPushButton#cancel {{ background: rgba(255,255,255,14); color: #DDE2FF; border: 1px solid rgba(255,255,255,32); }}
            QPushButton#cancel:hover {{ background: rgba(255,255,255,28); }}
            QPushButton#save {{
                color: white; border: none;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:1 {c2});
            }}
            QPushButton#save:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c1}, stop:0.4 {c1}, stop:1 {c2});
            }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 6px 2px; }}
            QScrollBar::handle:vertical {{ background: rgba(255,255,255,60); border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c1, c2 = type_colors(self.current_type)
        r = QRectF(self.rect()).adjusted(9, 9, -9, -9)
        p.setPen(Qt.NoPen)
        for i in range(9, 0, -1):   # soft coloured glow
            p.setBrush(with_alpha(c1, 6))
            p.drawRoundedRect(r.adjusted(-i, -i, i, i), 24 + i, 24 + i)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, QColor(30, 33, 58, 248))
        bg.setColorAt(1, QColor(11, 12, 26, 250))
        p.setBrush(bg)
        p.drawRoundedRect(r, 24, 24)
        wash = QRadialGradient(r.topLeft() + QPointF(70, 0), r.width() * 0.85)
        wash.setColorAt(0, with_alpha(c1, 60))
        wash.setColorAt(1, with_alpha(c1, 0))
        p.setBrush(wash)
        p.drawRoundedRect(r, 24, 24)
        border = QLinearGradient(r.topLeft(), r.bottomRight())
        border.setColorAt(0, with_alpha(c1, 230))
        border.setColorAt(0.5, with_alpha(c2, 70))
        border.setColorAt(1, with_alpha(c2, 200))
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(border, 1.6))
        p.drawRoundedRect(r, 24, 24)

