"""Palette, typography and easing helpers shared across the UI."""
import math
import re

from PySide6.QtGui import QColor, QFont, QFontDatabase

# Every sticky-note type gets its own gradient (c1 -> c2) and glyph.
NOTE_TYPES = {
    "todo":     {"label": "To Do",     "icon": "✔", "c1": "#FFB627", "c2": "#F2541B"},
    "task":     {"label": "Task",      "icon": "⚑", "c1": "#36D6FF", "c2": "#2F55F4"},
    "project":  {"label": "Project",   "icon": "◈", "c1": "#C77DFF", "c2": "#6328E0"},
    "followup": {"label": "Follow Up", "icon": "↻", "c1": "#FF6FAE", "c2": "#E0144C"},
    "email":    {"label": "Email",     "icon": "✉", "c1": "#2EE6A0", "c2": "#08877C"},
}
TYPE_ORDER = tuple(NOTE_TYPES)
ACCENT = ("#9AA8FF", "#5B4DFF")

_ALIASES = {
    "todo": "todo", "todos": "todo",
    "task": "task", "tasks": "task",
    "project": "project", "projects": "project",
    "followup": "followup", "followups": "followup", "follow": "followup",
    "email": "email", "emails": "email", "mail": "email",
}


def normalize_type(raw):
    key = re.sub(r"[^a-z]", "", str(raw or "").lower())
    return _ALIASES.get(key, "todo")


def type_colors(key):
    if key is None:
        return QColor(ACCENT[0]), QColor(ACCENT[1])
    info = NOTE_TYPES.get(key, NOTE_TYPES["todo"])
    return QColor(info["c1"]), QColor(info["c2"])


# ── typography ──────────────────────────────────────────────────────────────
_family = None


def family():
    global _family
    if _family is None:
        available = set(QFontDatabase.families())
        for name in ("Segoe UI Variable Display", "Segoe UI", "Inter", "Helvetica Neue", "Arial"):
            if name in available:
                _family = name
                break
        else:
            _family = QFont().family()
    return _family


def font(px, weight=QFont.Normal, spacing=0.0):
    f = QFont(family())
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return f


# ── maths ───────────────────────────────────────────────────────────────────
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def lerp(a, b, t):
    return a + (b - a) * t


def ease_out_cubic(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_in_out(t):
    t = clamp(t)
    return 4 * t * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def ease_out_back(t, s=1.70158):
    t = clamp(t) - 1
    return t * t * ((s + 1) * t + s) + 1


def norm_angle(a):
    """Wrap degrees into [-180, 180)."""
    return (a + 180.0) % 360.0 - 180.0


def mix(a, b, t):
    t = clamp(t)
    return QColor(
        int(lerp(a.red(), b.red(), t)),
        int(lerp(a.green(), b.green(), t)),
        int(lerp(a.blue(), b.blue(), t)),
        int(lerp(a.alpha(), b.alpha(), t)),
    )


def with_alpha(c, a):
    c = QColor(c)
    c.setAlpha(int(clamp(a, 0, 255)))
    return c


def hypot(p, q):
    return math.hypot(p.x() - q.x(), p.y() - q.y())
