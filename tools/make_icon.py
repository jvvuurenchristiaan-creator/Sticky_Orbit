"""Render the orb into assets/stickyorb.ico for the EXE."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402

from stickyorb.gfx import draw_orb  # noqa: E402

app = QGuiApplication([])
img = QImage(256, 256, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
draw_orb(p, QPointF(128, 128), 62, 1.0, {}, 0, glyph="✦")
p.end()
out = ROOT / "assets" / "stickyorb.ico"
out.parent.mkdir(exist_ok=True)
if not img.save(str(out), "ICO"):
    img.save(str(out.with_suffix(".png")))
    sys.exit("ICO writer unavailable; saved PNG instead")
print(f"Icon written to {out}")
