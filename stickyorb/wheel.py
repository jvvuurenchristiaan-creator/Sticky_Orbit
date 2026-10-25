"""The radial note wheel: a spinning carousel of sticky notes around a glass hub."""
import math
import random
import time

from PySide6.QtCore import QElapsedTimer, QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor, QFont, QFontMetricsF, QGuiApplication,
                           QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import QWidget

from .editor import EditorPanel
from .gfx import CARD_H, CARD_W, card_path, draw_orb, draw_text_block, md_preview, relative_time, render_card
from .orb import OrbWidget, anim_time
from .store import Note
from .theme import (ACCENT, NOTE_TYPES, TYPE_ORDER, clamp, ease_out_back, ease_out_cubic, font, hypot, mix,
                    norm_angle, type_colors, with_alpha)

DESIGN = 900.0            # everything is laid out in a 900×900 design space, then scaled
C = QPointF(450, 450)
OUTER_R = 440
RING_R = 292
HUB_R = 198
TICK_R = 372
PILL_R = 404
MAX_WRAP = 12             # up to this many notes share the full circle; beyond, the ring scrolls
X_BTN = QPointF(CARD_W / 2 - 15, -CARD_H / 2 + 15)
CARD_CLIP = card_path(ox=-CARD_W / 2, oy=-CARD_H / 2)


class Card:
    __slots__ = ("note", "angle", "birth", "hover", "inv", "world", "pos", "dying")

    def __init__(self, note, angle, birth=1.0):
        self.note, self.angle, self.birth = note, angle, birth
        self.hover = 0.0
        self.inv = self.world = self.pos = None
        self.dying = 0.0


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "size", "color")


class Star:
    __slots__ = ("ang", "rad", "speed", "size", "phase", "tw", "color")


class WheelWindow(QWidget):
    closed = Signal()
    notes_changed = Signal(list)
    context_requested = Signal(QPoint)

    def __init__(self, store):
        super().__init__(None, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setWindowTitle("Sticky Orb")

        self.store = store
        self.notes = store.load_all()
        self.filter = None
        self.visible_notes = []
        self.cards = {}
        self.dying = []
        self.paint_order = []
        self.particles = []
        self.stars = [self._make_star() for _ in range(120)]
        self.pixcache = {}

        self.rot = self.rot_target = self.rot_vel = 0.0
        self.open_t, self.opening = 0.0, False
        self.t = 0.0
        self.s = 1.0
        self.orb_pt = QPointF(52, 52)
        self.hub_color = type_colors(None)[0]
        self.hub_id, self.hub_fade = None, 1.0
        self.edit_t = 0.0
        self.hover = None
        self.press = None
        self.dragging = False
        self.drag_vel = 0.0
        self.wheel_accum = 0
        self.away = 0.0
        self.toast = None
        self.design_inv = QTransform()
        self.hit_regions = []

        self.editor = EditorPanel(self)
        self.editor.saved.connect(self._on_editor_saved)
        self.editor.closed.connect(self.setFocus)

        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self._tick)
        self._rebuild()

    # ── show / hide ─────────────────────────────────────────────────────────
    def show_wheel(self, orb_global):
        screen = QGuiApplication.screenAt(orb_global) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry()
        self.s = min(1.0, (avail.height() - 12) / DESIGN, (avail.width() - 12) / DESIGN)
        size = int(DESIGN * self.s)
        self.setFixedSize(size, size)
        origin = QPoint(avail.right() - size + 1, avail.top())
        self.move(origin)
        self.orb_pt = QPointF(orb_global - origin) / self.s

        focused = self._focused_note()
        fresh = self.store.load_all()          # pick up edits made outside the app
        self.notes = fresh
        self._rebuild(keep_id=focused.id if focused else None)
        self.notes_changed.emit(self.notes)

        w, h = int(min(580, size * 0.74)), int(min(500, size * 0.66))
        self.editor.setGeometry((size - w) // 2, (size - h) // 2, w, h)

        if not self.isVisible():
            self.open_t = 0.0
            self._burst(self.orb_pt, None, 36, speed=(40, 220))
        self.opening = True
        self.away = 0.0
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.clock.restart()
        self.timer.start(16)

    def hide_wheel(self):
        if self.editor.isVisible():
            self.editor.cancel()
        self.opening = False

    def _finish_hide(self):
        self.timer.stop()
        self.hide()
        self.toast = None
        self.particles.clear()
        self.dying.clear()
        self.closed.emit()

    # ── model helpers ───────────────────────────────────────────────────────
    def _spacing(self):
        n = len(self.visible_notes)
        return 360.0 / n if 0 < n <= MAX_WRAP else 360.0 / MAX_WRAP

    def _wrap(self):
        return len(self.visible_notes) <= MAX_WRAP

    def _focus_index(self, use_target=False):
        n = len(self.visible_notes)
        if not n:
            return -1
        i = int(round((self.rot_target if use_target else self.rot) / self._spacing()))
        return i % n if self._wrap() else int(clamp(i, 0, n - 1))

    def _focused_note(self, use_target=True):
        i = self._focus_index(use_target)
        return self.visible_notes[i] if i >= 0 else None

    def _target_angle(self, i):
        a = i * self._spacing() - self.rot
        return norm_angle(a) if self._wrap() else a

    def _rebuild(self, keep_id=None, keep_index=None):
        old_focus = self._focus_index(True)
        self.visible_notes = [n for n in self.notes if self.filter in (None, n.type)]
        ids = {n.id for n in self.visible_notes}
        for nid in [k for k in self.cards if k not in ids]:
            card = self.cards.pop(nid)
            if self.isVisible() and card.world is not None:
                card.dying = 0.0
                self.dying.append(card)
        n = len(self.visible_notes)
        if not n:
            self.rot = self.rot_target = self.rot_vel = 0.0
            return
        pos = {note.id: i for i, note in enumerate(self.visible_notes)}
        if keep_id in pos:
            idx = pos[keep_id]
        else:
            idx = int(clamp(old_focus if keep_index is None else keep_index, 0, n - 1))
        self.rot = self.rot_target = idx * self._spacing()
        self.rot_vel = 0.0
        for i, note in enumerate(self.visible_notes):
            card = self.cards.get(note.id)
            if card is None:
                self.cards[note.id] = Card(note, self._target_angle(i), 0.0 if self.isVisible() else 1.0)
            else:
                card.note = note

    def _sort(self):
        self.notes.sort(key=lambda n: n.created, reverse=True)

    def step(self, d):
        n = len(self.visible_notes)
        if not n:
            return
        sp = self._spacing()
        base = round(self.rot_target / sp) + d
        if not self._wrap():
            base = clamp(base, 0, n - 1)
        self.rot_target = base * sp

    def focus_on(self, i):
        sp = self._spacing()
        base = i * sp
        if self._wrap():
            base += round((self.rot_target - base) / 360.0) * 360.0
        self.rot_target = base

    # ── actions ─────────────────────────────────────────────────────────────
    def new_note(self):
        if not self.editor.isVisible():
            self.activateWindow()
            self.editor.open_for(None, self.filter or "todo")

    def edit_note(self, note):
        if note and not self.editor.isVisible():
            self.activateWindow()
            self.editor.open_for(note)

    def _on_editor_saved(self, note, title, kind, content):
        if note is None:
            note = Note(title=title, type=kind, content=content)
            self.store.save(note)
            self.notes.append(note)
            fresh = True
        else:
            note.title, note.type, note.content = title, kind, content
            self.store.save(note)
            fresh = False
        self._sort()
        if self.filter and self.filter != note.type:
            self.filter = None
        self._rebuild(keep_id=note.id)
        card = self.cards[note.id]
        if fresh:
            card.birth = 0.0
            self._burst(C, note.type, 80, speed=(120, 420))
        else:
            self._burst(card.pos or C, note.type, 40)
        self.notes_changed.emit(self.notes)

    def archive_note(self, note_id):
        note = next((n for n in self.notes if n.id == note_id), None)
        if note is None:
            return
        card = self.cards.get(note_id)
        idx = self.visible_notes.index(note) if note in self.visible_notes else 0
        focus = self._focus_index(True)
        self.store.archive(note)
        self.notes.remove(note)
        if card and card.pos is not None:
            self._burst(card.pos, note.type, 70, speed=(60, 360))
        self._rebuild(keep_index=focus - (1 if idx < focus else 0))
        self.toast = {"note": note, "life": 6.0}
        self.notes_changed.emit(self.notes)

    def _undo(self):
        if not self.toast:
            return
        note = self.toast["note"]
        self.toast = None
        self.store.restore(note)
        self.notes.append(note)
        self._sort()
        if self.filter and self.filter != note.type:
            self.filter = None
        self._rebuild(keep_id=note.id)
        self.cards[note.id].birth = 0.0
        self._burst(C + QPointF(0, -RING_R), note.type, 60)
        self.notes_changed.emit(self.notes)

    def set_filter(self, key):
        focused = self._focused_note()
        self.filter = None if key is None or self.filter == key else key
        self._rebuild(keep_id=focused.id if focused else None)

    def _burst(self, pos, kind, count, speed=(60, 320)):
        if kind is None:
            cols = [type_colors(k)[0] for k in TYPE_ORDER] + [QColor(255, 255, 255)]
        else:
            c1, c2 = type_colors(kind)
            cols = [c1, c2, c1.lighter(140), QColor(255, 255, 255)]
        for _ in range(count):
            a = random.uniform(0, math.tau)
            v = random.uniform(*speed)
            pt = Particle()
            pt.x, pt.y = pos.x(), pos.y()
            pt.vx, pt.vy = math.cos(a) * v, math.sin(a) * v
            pt.life = pt.max_life = random.uniform(0.5, 1.25)
            pt.size = random.uniform(1.2, 3.6)
            pt.color = random.choice(cols)
            self.particles.append(pt)

    @staticmethod
    def _make_star():
        st = Star()
        st.ang = random.uniform(0, math.tau)
        st.rad = 110 + 320 * math.sqrt(random.random())
        st.speed = random.uniform(0.01, 0.06) * random.choice((-1, 1))
        st.size = random.uniform(0.5, 2.0)
        st.phase = random.uniform(0, math.tau)
        st.tw = random.uniform(0.8, 3.0)
        st.color = (QColor(255, 255, 255) if random.random() < 0.65
                    else type_colors(random.choice(TYPE_ORDER))[0].lighter(130))
        return st

    # ── animation loop ──────────────────────────────────────────────────────
    def _tick(self):
        dt = min(0.05, self.clock.restart() / 1000.0)
        self.t += dt

        if self.opening:
            self.open_t = min(1.0, self.open_t + dt / 0.6)
        else:
            self.open_t = max(0.0, self.open_t - dt / 0.3)
            if self.open_t <= 0.0:
                self._finish_hide()
                return

        if not self.dragging:   # critically-ish damped spring with a little bounce
            k = 120.0
            d = 2 * math.sqrt(k) * 0.7
            self.rot_vel += (k * (self.rot_target - self.rot) - d * self.rot_vel) * dt
            self.rot += self.rot_vel * dt

        wrap = self._wrap()
        hovered = self.hover[1] if self.hover and self.hover[0] in ("card", "x") else None
        for i, note in enumerate(self.visible_notes):
            card = self.cards[note.id]
            tgt = self._target_angle(i)
            diff = norm_angle(tgt - card.angle) if wrap else tgt - card.angle
            card.angle += diff * min(1.0, dt * 18)
            if wrap:
                card.angle = norm_angle(card.angle)
            card.birth = min(1.0, card.birth + dt * 2.0)
            card.hover += ((1.0 if note.id == hovered else 0.0) - card.hover) * min(1.0, dt * 12)
        for card in self.dying:
            card.dying += dt * 2.4
        self.dying = [c for c in self.dying if c.dying < 1.0]

        drag = 1 - 2.4 * dt
        for pt in self.particles:
            pt.x += pt.vx * dt
            pt.y += pt.vy * dt
            pt.vx *= drag
            pt.vy *= drag
            pt.life -= dt
        self.particles = [pt for pt in self.particles if pt.life > 0]

        focused = self._focused_note(False)
        self.hub_color = mix(self.hub_color, type_colors(focused.type if focused else None)[0], dt * 6)
        fid = focused.id if focused else None
        if fid != self.hub_id:
            self.hub_id, self.hub_fade = fid, 0.0
        self.hub_fade = min(1.0, self.hub_fade + dt * 4.5)
        self.edit_t += ((1.0 if self.editor.isVisible() else 0.0) - self.edit_t) * min(1.0, dt * 10)

        if self.toast:
            self.toast["life"] -= dt
            if self.toast["life"] <= 0:
                self.toast = None

        self._update_hover()
        self._auto_close(dt)
        self.update()

    def _cursor_local(self):
        return QPointF(self.mapFromGlobal(QCursor.pos()))

    def _update_hover(self):
        if self.editor.isVisible() or self.open_t < 0.9 or self.dragging:
            new = None
        else:
            pos = self._cursor_local()
            new = self._hit(pos) if self.rect().contains(pos.toPoint()) else None
        if new != self.hover:
            self.hover = new
            if not self.dragging:
                clickable = new is not None and new[0] not in ("ring", "hub")
                self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)

    def _auto_close(self, dt):
        if not self.opening or self.editor.isVisible() or self.dragging or self.open_t < 1.0:
            self.away = 0.0
            return
        d = self.design_inv.map(self._cursor_local())
        inside = hypot(d, C) < OUTER_R + 12 or hypot(d, self.orb_pt) < 70 / self.s
        self.away = 0.0 if inside else self.away + dt
        if self.away > 0.55:
            self.hide_wheel()

    # ── hit testing ─────────────────────────────────────────────────────────
    def _hit(self, pos):
        d = self.design_inv.map(pos)
        for key, shape in self.hit_regions:
            if isinstance(shape, QRectF):
                if shape.contains(d):
                    return key
            elif hypot(d, shape[0]) <= shape[1]:
                return key
        for card in reversed(self.paint_order):
            if card.inv is None:
                continue
            lp = card.inv.map(pos)
            if abs(lp.x()) <= CARD_W / 2 and abs(lp.y()) <= CARD_H / 2:
                if hypot(lp, X_BTN) <= 13:
                    return ("x", card.note.id)
                return ("card", card.note.id)
        dist = hypot(d, C)
        if dist <= OUTER_R:
            return ("ring",) if dist > HUB_R else ("hub",)
        return None

    def _angle_of(self, d):
        return math.degrees(math.atan2(d.y() - C.y(), d.x() - C.x()))

    # ── input ───────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if self.editor.isVisible():
            return
        if e.button() == Qt.RightButton:
            self.context_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        pos = e.position()
        ang = self._angle_of(self.design_inv.map(pos))
        self.press = {"hit": self._hit(pos), "pos": pos, "moved": False,
                      "last_ang": ang, "last_t": time.perf_counter()}
        self.drag_vel = 0.0

    def mouseMoveEvent(self, e):
        pr = self.press
        if not pr:
            return
        if not pr["moved"]:
            delta = e.position() - pr["pos"]
            draggable = pr["hit"] and pr["hit"][0] in ("card", "ring", "hub")
            if draggable and abs(delta.x()) + abs(delta.y()) > 6 and self.visible_notes:
                pr["moved"] = True
                self.dragging = True
                self.hover = None
                self.setCursor(Qt.ClosedHandCursor)
        if self.dragging:
            ang = self._angle_of(self.design_inv.map(e.position()))
            delta = norm_angle(ang - pr["last_ang"])
            now = time.perf_counter()
            dtm = max(1e-3, now - pr["last_t"])
            pr["last_ang"], pr["last_t"] = ang, now
            self.rot -= delta
            if not self._wrap():
                sp = self._spacing()
                self.rot = clamp(self.rot, -sp * 0.4, (len(self.visible_notes) - 1 + 0.4) * sp)
            self.drag_vel = 0.6 * self.drag_vel + 0.4 * (-delta / dtm)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or not self.press:
            return
        pr, self.press = self.press, None
        if self.dragging:
            self.dragging = False
            self.setCursor(Qt.ArrowCursor)
            sp = self._spacing()
            i = round((self.rot + self.drag_vel * 0.22) / sp)
            if not self._wrap():
                i = clamp(i, 0, len(self.visible_notes) - 1)
            self.rot_target = i * sp
            self.rot_vel = clamp(self.drag_vel, -1500, 1500)
            return
        hit = self._hit(e.position())
        if hit is not None and hit == pr["hit"]:
            self._activate(hit)

    def mouseDoubleClickEvent(self, e):
        if self.editor.isVisible():
            return
        hit = self._hit(e.position())
        if hit and hit[0] == "card":
            self.edit_note(next((n for n in self.notes if n.id == hit[1]), None))

    def _activate(self, hit):
        kind = hit[0]
        if kind == "x":
            self.archive_note(hit[1])
        elif kind == "card":
            i = next((j for j, n in enumerate(self.visible_notes) if n.id == hit[1]), -1)
            if i == self._focus_index(True):
                self.edit_note(self.visible_notes[i])
            elif i >= 0:
                self.focus_on(i)
        elif kind == "pill":
            self.set_filter(hit[1])
        elif kind == "new":
            self.new_note()
        elif kind == "edit":
            self.edit_note(self._focused_note())
        elif kind == "undo":
            self._undo()
        elif kind == "orb":
            self.hide_wheel()

    def wheelEvent(self, e):
        if self.editor.isVisible():
            return
        d = e.angleDelta()
        self.wheel_accum += d.y() or d.x()
        while abs(self.wheel_accum) >= 120:
            sign = 1 if self.wheel_accum > 0 else -1
            self.step(-sign)
            self.wheel_accum -= 120 * sign

    def keyPressEvent(self, e):
        if self.editor.isVisible():
            return super().keyPressEvent(e)
        k = e.key()
        if k in (Qt.Key_Left, Qt.Key_Up):
            self.step(-1)
        elif k in (Qt.Key_Right, Qt.Key_Down):
            self.step(1)
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.edit_note(self._focused_note())
        elif k in (Qt.Key_N, Qt.Key_Plus, Qt.Key_Insert):
            self.new_note()
        elif k == Qt.Key_Delete:
            note = self._focused_note()
            if note:
                self.archive_note(note.id)
        elif k == Qt.Key_Z and e.modifiers() & Qt.ControlModifier:
            self._undo()
        elif Qt.Key_0 <= k <= Qt.Key_5:
            i = k - Qt.Key_0
            self.set_filter(None if i == 0 else TYPE_ORDER[i - 1])
        elif k == Qt.Key_Escape:
            self.hide_wheel()
        else:
            super().keyPressEvent(e)

    # ── painting ────────────────────────────────────────────────────────────
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        k = 0.12 + 0.88 * ease_out_cubic(self.open_t)
        p.scale(self.s, self.s)
        p.translate(self.orb_pt)
        p.scale(k, k)
        p.translate(-self.orb_pt)
        self.design_inv = p.transform().inverted()[0]
        self.hit_regions = []
        p.setOpacity(clamp(self.open_t * 1.8))

        self._paint_backdrop(p)
        self._paint_rings(p)
        self._paint_cards(p)
        self._paint_hub(p)
        self._paint_pills(p)
        self._paint_toast(p)
        self._paint_particles(p)
        if self.edit_t > 0.01:
            veil = QRadialGradient(C, OUTER_R)
            veil.setColorAt(0.0, QColor(4, 5, 12, int(170 * self.edit_t)))
            veil.setColorAt(0.9, QColor(4, 5, 12, int(150 * self.edit_t)))
            veil.setColorAt(1.0, QColor(4, 5, 12, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(veil)
            p.drawEllipse(C, OUTER_R, OUTER_R)
        self._paint_mini_orb(p)

    def _paint_backdrop(self, p):
        p.setPen(Qt.NoPen)
        g = QRadialGradient(C, OUTER_R)
        g.setColorAt(0.00, QColor(18, 20, 42, 240))
        g.setColorAt(0.78, QColor(11, 12, 27, 234))
        g.setColorAt(0.93, QColor(8, 9, 20, 200))
        g.setColorAt(1.00, QColor(6, 7, 16, 0))
        p.setBrush(g)
        p.drawEllipse(C, OUTER_R, OUTER_R)

        p.save()
        clip = QPainterPath()
        clip.addEllipse(C, OUTER_R - 12, OUTER_R - 12)
        p.setClipPath(clip)
        for j, kind in enumerate(("project", "task", "followup")):
            a = self.t * 0.11 + j * 2.094
            pt = C + QPointF(math.cos(a) * 170, math.sin(a * 1.3) * 150)
            col = type_colors(kind)[0]
            ng = QRadialGradient(pt, 280)
            ng.setColorAt(0, with_alpha(col, 42))
            ng.setColorAt(1, with_alpha(col, 0))
            p.setBrush(ng)
            p.drawEllipse(pt, 280, 280)
        aura = QRadialGradient(C, 360)
        aura.setColorAt(0, with_alpha(self.hub_color, 40))
        aura.setColorAt(1, with_alpha(self.hub_color, 0))
        p.setBrush(aura)
        p.drawEllipse(C, 360, 360)
        for st in self.stars:
            a = st.ang + self.t * st.speed
            pt = C + QPointF(math.cos(a) * st.rad, math.sin(a) * st.rad)
            alpha = 50 + 170 * (0.5 + 0.5 * math.sin(self.t * st.tw + st.phase))
            if st.size > 1.5:
                p.setBrush(with_alpha(st.color, alpha * 0.22))
                p.drawEllipse(pt, st.size * 3, st.size * 3)
            p.setBrush(with_alpha(st.color, alpha))
            p.drawEllipse(pt, st.size, st.size)
        p.restore()

    def _paint_rings(self, p):
        col = self.hub_color
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 18), 1.2))
        p.drawEllipse(C, RING_R, RING_R)
        for offset, colour, alpha in ((0, col, 230), (180, QColor(255, 255, 255), 120)):
            comet = QConicalGradient(C, -self.t * 40 + offset)
            comet.setColorAt(0.0, with_alpha(colour, alpha))
            comet.setColorAt(0.22, with_alpha(colour, 0))
            comet.setColorAt(0.995, with_alpha(colour, 0))
            comet.setColorAt(1.0, with_alpha(colour, alpha))
            p.setPen(QPen(QBrush(comet), 2.4))
            p.drawEllipse(C, RING_R, RING_R)

        spin = self.t * 4
        p.save()
        p.translate(C)
        p.rotate(spin)
        for i in range(180):
            ang = i * 2.0
            near = clamp(1 - abs(norm_angle(ang + spin + 90)) / 28)
            major = i % 5 == 0
            length = (9 if major else 4) + near * 7
            base = QColor(255, 255, 255, 70 if major else 34)
            p.setPen(QPen(mix(base, with_alpha(col, 235), near), 1.6 if major else 1.0))
            rad = math.radians(ang)
            cs, sn = math.cos(rad), math.sin(rad)
            p.drawLine(QPointF(cs * TICK_R, sn * TICK_R), QPointF(cs * (TICK_R + length), sn * (TICK_R + length)))
        p.restore()

        arc = QRectF(C.x() - TICK_R + 10, C.y() - TICK_R + 10, 2 * (TICK_R - 10), 2 * (TICK_R - 10))
        p.setPen(QPen(with_alpha(col, 45), 10, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc, 70 * 16, 40 * 16)
        p.setPen(QPen(with_alpha(col, 220), 2.6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(arc, 72 * 16, 36 * 16)

    def _card_pixmap(self, note):
        key = (note.id, note.title, note.type, note.content, round(self.s, 3))
        entry = self.pixcache.get(key)
        if entry is None:
            factor = 1.3 * self.s * self.devicePixelRatioF()
            pm = QPixmap(int(CARD_W * factor) + 2, int(CARD_H * factor) + 2)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
            q.scale(factor, factor)
            render_card(q, note)
            q.end()
            if len(self.pixcache) > 300:
                self.pixcache.clear()
            entry = self.pixcache[key] = (pm, factor)
        return entry

    def _draw_card(self, p, card, focus):
        note = card.note
        c1, _ = type_colors(note.type)
        p.setPen(Qt.NoPen)
        glow = QRadialGradient(QPointF(0, 4), CARD_W * 0.85)
        glow.setColorAt(0, with_alpha(c1, 60 + 120 * focus + 60 * card.hover))
        glow.setColorAt(1, with_alpha(c1, 0))
        p.setBrush(glow)
        p.drawEllipse(QPointF(0, 4), CARD_W * 0.85, CARD_W * 0.68)
        shade = QRadialGradient(QPointF(0, 12), CARD_W * 0.62)
        shade.setColorAt(0, QColor(0, 0, 0, 120))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(shade)
        p.drawEllipse(QPointF(0, 12), CARD_W * 0.62, CARD_H * 0.62)

        pm, factor = self._card_pixmap(note)
        p.drawPixmap(QRectF(-CARD_W / 2, -CARD_H / 2, CARD_W, CARD_H), pm,
                     QRectF(0, 0, CARD_W * factor, CARD_H * factor))

        shine = max(focus, card.hover)
        if shine > 0.05:   # a sweep of light across focused / hovered cards
            p.save()
            p.setClipPath(CARD_CLIP)
            phase = (self.t * 0.45 + (hash(note.id) % 100) / 100.0) % 1.8 - 0.4
            x = -CARD_W / 2 + phase * CARD_W
            band = QLinearGradient(QPointF(x - 34, -CARD_H / 2), QPointF(x + 34, CARD_H / 2))
            band.setColorAt(0, QColor(255, 255, 255, 0))
            band.setColorAt(0.5, QColor(255, 255, 255, int(70 * shine)))
            band.setColorAt(1, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(-CARD_W / 2, -CARD_H / 2, CARD_W, CARD_H), band)
            p.restore()

        if card.hover > 0.02:
            on_x = self.hover == ("x", note.id)
            p.save()
            p.setOpacity(p.opacity() * card.hover)
            p.setBrush(QColor(255, 64, 100, 240) if on_x else QColor(8, 8, 20, 150))
            p.setPen(QPen(QColor(255, 255, 255, 220 if on_x else 130), 1))
            p.drawEllipse(X_BTN, 10.5 + (1.5 if on_x else 0), 10.5 + (1.5 if on_x else 0))
            p.setPen(QPen(QColor(255, 255, 255), 1.8, Qt.SolidLine, Qt.RoundCap))
            d = 4.0
            p.drawLine(X_BTN + QPointF(-d, -d), X_BTN + QPointF(d, d))
            p.drawLine(X_BTN + QPointF(-d, d), X_BTN + QPointF(d, -d))
            p.restore()

    def _paint_cards(self, p):
        base_opacity = p.opacity()
        for card in self.dying:
            if card.world is None:
                continue
            e = ease_out_cubic(card.dying)
            p.save()
            p.setTransform(card.world)
            p.rotate(e * 14)
            p.scale(1 + 0.35 * e, 1 + 0.35 * e)
            p.setOpacity(base_opacity * (1 - e))
            self._draw_card(p, card, 0.0)
            p.restore()

        wrap = self._wrap()
        drawn = []
        for note in self.visible_notes:
            card = self.cards[note.id]
            a = card.angle
            focus = max(0.0, math.cos(math.radians(a))) ** 2
            ad = min(abs(a), 180.0) / 180.0
            o = clamp((self.open_t - ad * 0.38) / 0.62)
            fade = 1.0 if wrap else clamp((172 - abs(a)) / 30)
            if fade <= 0 or o <= 0:
                card.inv = None
                continue
            pop = ease_out_back(card.birth)
            scale = ((0.58 + 0.56 * focus) * (0.25 + 0.75 * ease_out_back(o))
                     * (0.2 + 0.8 * pop) * (1 + 0.07 * card.hover))
            r = RING_R * ease_out_cubic(o) + 8 * card.hover
            th = math.radians(-90 + a)
            pos = C + QPointF(math.cos(th) * r, math.sin(th) * r)
            tilt = math.sin(math.radians(a)) * 10 * (1 - focus)
            alpha = min(1.0, o * 1.4) * fade * min(1.0, card.birth * 2 + 0.2) * (1 - 0.35 * ad)
            drawn.append((scale, card, pos, tilt, alpha, focus))
        drawn.sort(key=lambda item: item[0])
        self.paint_order = []
        for scale, card, pos, tilt, alpha, focus in drawn:
            p.save()
            p.translate(pos)
            p.rotate(tilt)
            p.scale(scale, scale)
            card.world = p.transform()
            card.inv = card.world.inverted()[0]
            card.pos = pos
            p.setOpacity(base_opacity * alpha)
            self._draw_card(p, card, focus)
            p.restore()
            self.paint_order.append(card)

    def _paint_hub(self, p):
        col = self.hub_color
        p.setPen(Qt.NoPen)
        span = HUB_R + 60
        aura = QRadialGradient(C, span)
        aura.setColorAt(HUB_R / span * 0.92, with_alpha(col, 0))
        aura.setColorAt(HUB_R / span, with_alpha(col, 95))
        aura.setColorAt(1.0, with_alpha(col, 0))
        p.setBrush(aura)
        p.drawEllipse(C, span, span)

        disc = QRadialGradient(C + QPointF(-60, -80), HUB_R * 1.6)
        disc.setColorAt(0.0, QColor(38, 42, 76, 250))
        disc.setColorAt(0.55, QColor(17, 19, 39, 250))
        disc.setColorAt(1.0, QColor(8, 9, 20, 252))
        p.setBrush(disc)
        p.drawEllipse(C, HUB_R, HUB_R)
        swirl = QConicalGradient(C, -self.t * 18)
        for pos, a in ((0, 40), (0.25, 0), (0.5, 26), (0.75, 0), (1, 40)):
            swirl.setColorAt(pos, with_alpha(col, a))
        p.setBrush(swirl)
        p.drawEllipse(C, HUB_R - 2, HUB_R - 2)
        glass = QLinearGradient(C.x(), C.y() - HUB_R, C.x(), C.y())
        glass.setColorAt(0, QColor(255, 255, 255, 28))
        glass.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(glass)
        p.drawEllipse(C, HUB_R - 3, HUB_R - 3)

        rim = QConicalGradient(C, self.t * 50)
        for pos, c in ((0, with_alpha(col, 255)), (0.1, QColor(255, 255, 255, 230)), (0.22, with_alpha(col, 210)),
                       (0.5, with_alpha(col, 40)), (0.78, with_alpha(col, 170)), (1, with_alpha(col, 255))):
            rim.setColorAt(pos, c)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QBrush(rim), 2.6))
        p.drawEllipse(C, HUB_R, HUB_R)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.drawEllipse(C, HUB_R - 10, HUB_R - 10)

        tip = QPainterPath()
        tip.moveTo(C.x(), C.y() - HUB_R - 15)
        tip.lineTo(C.x() - 7, C.y() - HUB_R - 5)
        tip.lineTo(C.x() + 7, C.y() - HUB_R - 5)
        tip.closeSubpath()
        p.setPen(Qt.NoPen)
        p.fillPath(tip, with_alpha(col, 230))

        n = len(self.visible_notes)
        note = self._focused_note(False)
        e = ease_out_cubic(self.hub_fade)
        p.save()
        p.setOpacity(p.opacity() * e)
        p.translate(0, (1 - e) * 10)
        if note is None:
            self._paint_hub_empty(p, col)
        else:
            self._paint_hub_note(p, note, n)
        p.restore()

        self._hub_button(p, ("new",), C + QPointF(-44 if n else 0, 150), "+", primary=True)
        if n:
            self._hub_button(p, ("edit",), C + QPointF(44, 150), "✎")

    def _paint_hub_empty(self, p, col):
        p.setFont(font(54, QFont.Bold))
        p.setPen(with_alpha(col, 230))
        p.drawText(QRectF(C.x() - 100, C.y() - 130, 200, 70), Qt.AlignCenter, "✦")
        label = NOTE_TYPES[self.filter]["label"] if self.filter else None
        title = f"No {label} notes yet" if label else "Nothing here yet"
        draw_text_block(p, title, font(22, QFont.DemiBold), QRectF(C.x() - 160, C.y() - 52, 320, 34),
                        QColor(255, 255, 255), 1, align=Qt.AlignHCenter)
        draw_text_block(p, "Click + to capture your first note", font(13),
                        QRectF(C.x() - 160, C.y() - 12, 320, 40), QColor(220, 225, 255, 160), 2,
                        align=Qt.AlignHCenter)

    def _paint_hub_note(self, p, note, n):
        c1, c2 = type_colors(note.type)
        info = NOTE_TYPES[note.type]
        idx = self._focus_index(False)
        p.setFont(font(10, QFont.Medium, 2.5))
        p.setPen(QColor(255, 255, 255, 110))
        p.drawText(QRectF(C.x() - 100, C.y() - 168, 200, 16), Qt.AlignCenter, f"{idx + 1:02d}  /  {n:02d}")

        label = f"{info['icon']}  {info['label'].upper()}"
        pf = font(10, QFont.Bold, 1.6)
        w = QFontMetricsF(pf).horizontalAdvance(label) + 30
        pill = QRectF(C.x() - w / 2, C.y() - 142, w, 24)
        g = QLinearGradient(pill.topLeft(), pill.bottomRight())
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(pill, 12, 12)
        p.setFont(pf)
        p.setPen(QColor(255, 255, 255))
        p.drawText(pill, Qt.AlignCenter, label)

        draw_text_block(p, note.title, font(22, QFont.DemiBold), QRectF(C.x() - 158, C.y() - 108, 316, 62),
                        QColor(255, 255, 255), 2, align=Qt.AlignHCenter, vcenter=True)
        line = QLinearGradient(C.x() - 60, 0, C.x() + 60, 0)
        line.setColorAt(0, with_alpha(c1, 0))
        line.setColorAt(0.5, with_alpha(c1, 220))
        line.setColorAt(1, with_alpha(c1, 0))
        p.fillRect(QRectF(C.x() - 60, C.y() - 38, 120, 1.5), line)
        body = md_preview(note.content) or "No contents yet — click ✎ to write some."
        draw_text_block(p, body, font(13), QRectF(C.x() - 160, C.y() - 24, 320, 122),
                        QColor(225, 230, 255, 215), 6, align=Qt.AlignHCenter)
        p.setFont(font(10, QFont.Medium, 0.6))
        p.setPen(QColor(255, 255, 255, 105))
        p.drawText(QRectF(C.x() - 120, C.y() + 103, 240, 16), Qt.AlignCenter,
                   f"Edited {relative_time(note.updated)}")

    def _hub_button(self, p, key, center, glyph, primary=False):
        hov = self.hover == key
        r = 21 + (2 if hov else 0)
        col = self.hub_color
        p.setPen(Qt.NoPen)
        if hov:
            g = QRadialGradient(center, r * 2.2)
            g.setColorAt(0, with_alpha(col, 140))
            g.setColorAt(1, with_alpha(col, 0))
            p.setBrush(g)
            p.drawEllipse(center, r * 2.2, r * 2.2)
        if primary:
            fill = QLinearGradient(center - QPointF(r, r), center + QPointF(r, r))
            fill.setColorAt(0, col.lighter(115))
            fill.setColorAt(1, mix(col, QColor(20, 10, 60), 0.45))
            p.setBrush(fill)
            p.setPen(QPen(QColor(255, 255, 255, 110), 1))
        else:
            p.setBrush(QColor(255, 255, 255, 36 if hov else 18))
            p.setPen(QPen(with_alpha(col, 200), 1.3))
        p.drawEllipse(center, r, r)
        p.setFont(font(24 if primary else 18, QFont.DemiBold))
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(center.x() - r, center.y() - r - (2 if primary else 0), 2 * r, 2 * r), Qt.AlignCenter, glyph)
        self.hit_regions.append((key, (center, r + 2)))

    def _paint_pills(self, p):
        counts = {}
        for note in self.notes:
            counts[note.type] = counts.get(note.type, 0) + 1
        items = [(None, "All", len(self.notes))] + [(k, NOTE_TYPES[k]["label"], counts.get(k, 0)) for k in TYPE_ORDER]
        pf = font(11, QFont.DemiBold)
        fm = QFontMetricsF(pf)
        spread = 104.0
        for j, (key, label, count) in enumerate(items):
            ang = math.radians(90 + spread / 2 - j * spread / (len(items) - 1))
            pos = C + QPointF(math.cos(ang) * PILL_R, math.sin(ang) * PILL_R)
            text = f"{label}  {count}"
            w = fm.horizontalAdvance(text) + 34
            rect = QRectF(pos.x() - w / 2, pos.y() - 13, w, 26)
            c1, c2 = type_colors(key)
            active = self.filter == key
            hov = self.hover == ("pill", key)
            if active:
                g = QLinearGradient(rect.topLeft(), rect.bottomRight())
                g.setColorAt(0, c1)
                g.setColorAt(1, c2)
                p.setBrush(g)
                p.setPen(QPen(QColor(255, 255, 255, 120), 1))
            else:
                p.setBrush(QColor(255, 255, 255, 34 if hov else 14))
                p.setPen(QPen(with_alpha(c1, 210 if hov else 95), 1.1))
            p.drawRoundedRect(rect, 13, 13)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255) if active else c1)
            p.drawEllipse(QPointF(rect.left() + 13, rect.center().y()), 3.6, 3.6)
            p.setFont(pf)
            p.setPen(QColor(255, 255, 255) if active else QColor(228, 232, 255, 215))
            p.drawText(QRectF(rect.left() + 22, rect.top(), w - 26, 26), Qt.AlignVCenter | Qt.AlignLeft, text)
            self.hit_regions.append((("pill", key), rect.adjusted(-2, -2, 2, 2)))

    def _paint_toast(self, p):
        if not self.toast:
            return
        life = self.toast["life"]
        a = clamp(life / 0.4) * clamp((6.0 - life) / 0.2)
        note = self.toast["note"]
        rect = QRectF(C.x() - 132, C.y() + 214, 264, 32)
        p.save()
        p.setOpacity(p.opacity() * a)
        p.setBrush(QColor(16, 18, 36, 240))
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.drawRoundedRect(rect, 16, 16)
        tf = font(11)
        msg = QFontMetricsF(tf).elidedText(f"Archived “{note.title}”", Qt.ElideRight, 170)
        p.setFont(tf)
        p.setPen(QColor(230, 233, 255, 220))
        p.drawText(rect.adjusted(16, 0, -70, 0), Qt.AlignVCenter | Qt.AlignLeft, msg)
        hov = self.hover == ("undo",)
        p.setFont(font(11, QFont.Bold, 1.5))
        p.setPen(type_colors(note.type)[0].lighter(130 if hov else 110))
        p.drawText(rect.adjusted(0, 0, -16, 0), Qt.AlignVCenter | Qt.AlignRight, "UNDO")
        p.restore()
        self.hit_regions.append((("undo",), rect))

    def _paint_particles(self, p):
        p.setPen(Qt.NoPen)
        for pt in self.particles:
            a = pt.life / pt.max_life
            c = QPointF(pt.x, pt.y)
            p.setBrush(with_alpha(pt.color, 70 * a))
            p.drawEllipse(c, pt.size * 2.6, pt.size * 2.6)
            p.setBrush(with_alpha(pt.color, 255 * a))
            p.drawEllipse(c, pt.size * a + 0.4, pt.size * a + 0.4)

    def _paint_mini_orb(self, p):
        p.save()
        p.setTransform(QTransform().scale(self.s, self.s))
        p.setOpacity(1.0)
        r = OrbWidget.R / self.s
        hov = 1.0 if self.hover == ("orb",) else 0.0
        counts = {}
        for note in self.notes:
            counts[note.type] = counts.get(note.type, 0) + 1
        draw_orb(p, self.orb_pt, r * (1 + 0.1 * hov), anim_time(), counts, len(self.notes), hov,
                 glyph="×" if self.open_t > 0.5 else None)
        p.restore()
        self.hit_regions.append((("orb",), (self.orb_pt, r * 1.7)))
