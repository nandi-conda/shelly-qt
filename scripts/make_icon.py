"""Generate shelly_qt/icons/shelly-qt.svg (scallop shell + install badge) and PNG sizes.

Run: QT_QPA_PLATFORM=offscreen python scripts/make_icon.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "shelly_qt" / "icons"
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def shell_svg() -> str:
    hx, hy, r = 240.0, 340.0, 190.0
    n = 7
    a0, a1 = 22.0, 158.0
    pt = lambda ang, rad: (hx + rad * math.cos(math.radians(ang)), hy - rad * math.sin(math.radians(ang)))
    angs = [a0 + (a1 - a0) * i / n for i in range(n + 1)]
    wedges, ribs = [], []
    for i in range(n):
        x1, y1 = pt(angs[i], r)
        x2, y2 = pt(angs[i + 1], r)
        cx, cy = pt((angs[i] + angs[i + 1]) / 2, r * 1.13)
        fill = "url(#lobeA)" if i % 2 == 0 else "url(#lobeB)"
        wedges.append(f'<path d="M{hx:.1f},{hy:.1f} L{x1:.1f},{y1:.1f} Q{cx:.1f},{cy:.1f} {x2:.1f},{y2:.1f} Z" fill="{fill}"/>')
    for i in range(1, n):
        x, y = pt(angs[i], r * 0.98)
        ribs.append(f'<path d="M{hx:.1f},{hy - 6:.1f} L{x:.1f},{y:.1f}"/>')
    # outline of the whole fan
    edge = [f"M{hx:.1f},{hy:.1f}"]
    x, y = pt(angs[0], r)
    edge.append(f"L{x:.1f},{y:.1f}")
    for i in range(n):
        cx, cy = pt((angs[i] + angs[i + 1]) / 2, r * 1.13)
        x, y = pt(angs[i + 1], r)
        edge.append(f"Q{cx:.1f},{cy:.1f} {x:.1f},{y:.1f}")
    edge.append("Z")
    outline = " ".join(edge)

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <title>Shelly-Qt</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3fd6c1"/>
      <stop offset="1" stop-color="#11808f"/>
    </linearGradient>
    <linearGradient id="lobeA" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#fff8ec"/>
      <stop offset="1" stop-color="#ffd9b0"/>
    </linearGradient>
    <linearGradient id="lobeB" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffe6c9"/>
      <stop offset="1" stop-color="#f7b98a"/>
    </linearGradient>
    <linearGradient id="badge" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#24476b"/>
      <stop offset="1" stop-color="#132a44"/>
    </linearGradient>
  </defs>
  <rect x="24" y="24" width="464" height="464" rx="104" fill="url(#bg)"/>
  <g>
    <path d="M194,334 L164,360 Q158,380 178,384 L302,384 Q322,380 316,360 L286,334 Z" fill="#f2a877"/>
    <path d="{outline}" fill="#c9733f" transform="translate(0,8)" opacity="0.35"/>
    {"".join(wedges)}
    <g stroke="#d98c58" stroke-width="7" stroke-linecap="round" fill="none" opacity="0.85">{"".join(ribs)}</g>
    <path d="{outline}" fill="none" stroke="#b8622f" stroke-width="8" stroke-linejoin="round"/>
    <path d="M194,334 L164,360 Q158,380 178,384 L302,384 Q322,380 316,360 L286,334" fill="none" stroke="#b8622f" stroke-width="8" stroke-linejoin="round"/>
  </g>
  <circle cx="398" cy="398" r="72" fill="#14879a"/>
  <circle cx="398" cy="398" r="60" fill="url(#badge)"/>
  <path d="M398,362 L398,414 M374,392 L398,416 L422,392" fill="none" stroke="#ffffff" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M371,434 L425,434" stroke="#3fd6c1" stroke-width="11" stroke-linecap="round"/>
</svg>
'''


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    svg = OUT / "shelly-qt.svg"
    svg.write_text(shell_svg())
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    rend = QSvgRenderer(str(svg))
    for s in SIZES:
        img = QImage(s, s, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rend.render(p, QRectF(0, 0, s, s))
        p.end()
        img.save(str(OUT / f"shelly-qt-{s}.png"))
    print("wrote", svg, "and", len(SIZES), "PNGs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
