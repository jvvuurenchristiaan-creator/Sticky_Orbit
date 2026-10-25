"""Reusable painting routines: text layout, sticky-note cards and the orb."""
import math
import re
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontMetricsF, QLinearGradient,
                           QPainterPath, QPen, QRadialGradient, QTextLayout, QTextOption)

from .theme import NOTE_TYPES, TYPE_ORDER, font, mix, type_colors, with_alpha

CARD_W, CARD_H = 156.0, 112.0
FOLD = 20.0


def md_preview(text):
    """Flatten markdown into compact display text (checkboxes become glyphs)."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^#{1,6}\s*", "", s)
        s = re.sub(r"^[-*+]\s+\[[xX]\]\s*", "☑ ", s)
        s = re.sub(r"^[-*+]\s+\[\s\]\s*", "☐ ", s)
        s = re.sub(r"^[-*+]\s+", "• ", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
        s = re.sub(r"(\*\*|__|`|~~)", "", s)
        out.append(s)
    return "\n".join(out)


def relative_time(dt):
    secs = (datetime.now() - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    days = int(secs // 86400)
    if days < 7:
        return "yesterday" if days == 1 else f"{days} days ago"
    return dt.strftime("%d %b %Y")


def draw_text_block(p, text, fnt, rect, color, max_lines, align=Qt.AlignLeft, shadow=None, vcenter=False):
    """Word-wrapped text clipped to max_lines, eliding the last visible line."""
    if not text:
        return 0.0
    text = text.replace("\n", " ")
    layout = QTextLayout(text, fnt)
    opt = QTextOption(align)
    opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(opt)
    fm = QFontMetricsF(fnt)
    lh = fm.lineSpacing()
    max_lines = max(1, min(max_lines, int(rect.height() // lh)))
    lines = []
    layout.beginLayout()
    while len(lines) < max_lines:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(rect.width())
        line.setPosition(QPointF(0, len(lines) * lh))
        lines.append(line)
    layout.endLayout()
    if not lines:
        return 0.0
    last = lines[-1]
    truncated = last.textStart() + last.textLength() < len(text)
    oy = (rect.height() - len(lines) * lh) / 2 if vcenter else 0.0
    origin = rect.topLeft() + QPointF(0, oy)
    for i, line in enumerate(lines):
        if i == len(lines) - 1 and truncated:
            rest = text[line.textStart():].replace(" ", " ")
            el = fm.elidedText(rest, Qt.ElideRight, rect.width())
            w = fm.horizontalAdvance(el)
            x = rect.left() + ((rect.width() - w) / 2 if align & Qt.AlignHCenter else 0)
            base = QPointF(x, origin.y() + line.y() + fm.ascent())
            p.setFont(fnt)
            if shadow is not None:
                p.setPen(shadow)
                p.drawText(base + QPointF(0, 1), el)
            p.setPen(color)
            p.drawText(base, el)
        else:
            if shadow is not None:
                p.setPen(shadow)
                line.draw(p, origin + QPointF(0, 1))
            p.setPen(color)
            line.draw(p, origin)
    return len(lines) * lh


def card_path(w=CARD_W, h=CARD_H, r=14.0, fold=FOLD, ox=0.0, oy=0.0):
    """Rounded card outline with a dog-eared bottom-right corner."""
    path = QPainterPath()
    path.moveTo(ox + r, oy)
    path.lineTo(ox + w - r, oy)
    path.quadTo(ox + w, oy, ox + w, oy + r)
    path.lineTo(ox + w, oy + h - fold)
    path.lineTo(ox + w - fold, oy + h)
    path.lineTo(ox + r, oy + h)
    path.quadTo(ox, oy + h, ox, oy + h - r)
    path.lineTo(ox, oy + r)
    path.quadTo(ox, oy, ox + r, oy)
    path.closeSubpath()
    return path


def render_card(q, note):
    """Paint the static body of a card into (0, 0, CARD_W, CARD_H)."""
    w, h = CARD_W, CARD_H
    c1, c2 = type_colors(note.type)
    info = NOTE_TYPES[note.type]
    path = card_path()

    body = QLinearGradient(0, 0, w, h)
    body.setColorAt(0.0, c1.lighter(106))
    body.setColorAt(0.55, mix(c1, c2, 0.6))
    body.setColorAt(1.0, c2)
    q.fillPath(path, body)

    sheen = QLinearGradient(0, 0, 0, h * 0.55)
    sheen.setColorAt(0, QColor(255, 255, 255, 70))
    sheen.setColorAt(1, QColor(255, 255, 255, 0))
    q.fillPath(path, sheen)
    depth = QLinearGradient(0, h * 0.45, 0, h)
    depth.setColorAt(0, QColor(0, 0, 0, 0))
    depth.setColorAt(1, QColor(0, 0, 0, 60))
    q.fillPath(path, depth)

    q.save()
    q.setClipPath(path)
    q.setFont(font(78, QFont.Bold))
    q.setPen(QColor(255, 255, 255, 30))
    q.drawText(QRectF(w - 84, h - 98, 96, 96), Qt.AlignCenter, info["icon"])
    q.restore()

    # dog-ear
    flap = QPainterPath()
    flap.moveTo(w - FOLD, h - FOLD)
    flap.lineTo(w, h - FOLD)
    flap.lineTo(w - FOLD, h)
    flap.closeSubpath()
    fg = QLinearGradient(w - FOLD, h - FOLD, w - FOLD * 0.4, h - FOLD * 0.4)
    fg.setColorAt(0, c2.darker(150))
    fg.setColorAt(1, c1.lighter(135))
    q.fillPath(flap, fg)
    q.setPen(QPen(QColor(255, 255, 255, 120), 0.8))
    q.drawLine(QPointF(w, h - FOLD), QPointF(w - FOLD, h))

    q.setBrush(Qt.NoBrush)
    q.setPen(QPen(QColor(255, 255, 255, 95), 1.0))
    q.drawPath(path)

    shadow = QColor(0, 0, 0, 80)
    q.setFont(font(9, QFont.Bold, 1.4))
    q.setPen(shadow)
    hdr = f"{info['icon']}  {info['label'].upper()}"
    q.drawText(QRectF(12, 10, w - 50, 14), Qt.AlignLeft | Qt.AlignVCenter, hdr)
    q.setPen(QColor(255, 255, 255, 235))
    q.drawText(QRectF(12, 9, w - 50, 14), Qt.AlignLeft | Qt.AlignVCenter, hdr)

    draw_text_block(q, note.title, font(15, QFont.DemiBold), QRectF(12, 27, w - 28, 41),
                    QColor(255, 255, 255), 2, shadow=QColor(0, 0, 0, 90))
    draw_text_block(q, md_preview(note.content), font(11), QRectF(12, 70, w - 36, 32),
                    QColor(255, 255, 255, 220), 2, shadow=QColor(0, 0, 0, 70))


def draw_orb(p, c, r, t, type_counts, total, hover=0.0, glyph=None):
    """The glowing launcher orb: halo, rainbow ring, glass sphere, satellites."""
    p.save()
    p.setPen(Qt.NoPen)
    cols = [type_colors(k)[0] for k in TYPE_ORDER]
    ph = (t * 0.25) % len(cols)
    i = int(ph)
    glow = mix(cols[i], cols[(i + 1) % len(cols)], ph - i)
    pulse = 0.5 + 0.5 * math.sin(t * 2.2)

    gr = r * (2.0 + 0.25 * pulse + 0.35 * hover)
    halo = QRadialGradient(c, gr)
    halo.setColorAt(0.0, with_alpha(glow, 150 + 70 * hover))
    halo.setColorAt(0.45, with_alpha(glow, 55 + 30 * hover))
    halo.setColorAt(1.0, with_alpha(glow, 0))
    p.setBrush(halo)
    p.drawEllipse(c, gr, gr)

    ring = QConicalGradient(c, -t * 120)
    for j, col in enumerate(cols + [cols[0]]):
        ring.setColorAt(j / len(cols), col)
    p.setBrush(ring)
    p.drawEllipse(c, r + 3, r + 3)

    sphere = QRadialGradient(c + QPointF(-r * 0.35, -r * 0.45), r * 1.6)
    sphere.setColorAt(0.0, QColor("#4b5190"))
    sphere.setColorAt(0.45, QColor("#171a37"))
    sphere.setColorAt(1.0, QColor("#04050c"))
    p.setBrush(sphere)
    p.drawEllipse(c, r, r)

    swirl = QConicalGradient(c, t * 70)
    for pos, a in ((0, 95), (0.25, 0), (0.5, 60), (0.75, 0), (1, 95)):
        swirl.setColorAt(pos, with_alpha(glow, a))
    p.setBrush(swirl)
    p.drawEllipse(c, r * 0.92, r * 0.92)

    hc = c + QPointF(-r * 0.3, -r * 0.42)
    spec = QRadialGradient(hc, r * 0.6)
    spec.setColorAt(0, QColor(255, 255, 255, 170))
    spec.setColorAt(1, QColor(255, 255, 255, 0))
    p.setBrush(spec)
    p.drawEllipse(hc, r * 0.62, r * 0.44)

    label = glyph if glyph is not None else (str(total) if total else "+")
    p.setFont(font(r * (0.95 if glyph else 0.72), QFont.Bold))
    p.setPen(QColor(255, 255, 255, 240))
    p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), Qt.AlignCenter, label)

    active = [k for k in TYPE_ORDER if type_counts.get(k)]
    p.setPen(Qt.NoPen)
    for j, k in enumerate(active):
        a = t * (0.9 + 0.22 * j) + j * (2 * math.pi / len(active))
        orbit = r + 9 + 2 * hover
        pt = c + QPointF(math.cos(a) * orbit, math.sin(a) * orbit * 0.9)
        col = type_colors(k)[0]
        sg = QRadialGradient(pt, 6)
        sg.setColorAt(0, with_alpha(col, 200))
        sg.setColorAt(1, with_alpha(col, 0))
        p.setBrush(sg)
        p.drawEllipse(pt, 6, 6)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawEllipse(pt, 1.6, 1.6)
    p.restore()
