"""Generate shelly_qt/icons/shelly-qt.svg (neon nautilus) and PNG sizes.

Run: QT_QPA_PLATFORM=offscreen python scripts/make_icon.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "shelly_qt" / "icons"
SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def nautilus_svg() -> str:
    g = 3.0                               # growth per turn
    b = math.log(g) / (2 * math.pi)
    T = 4 * math.pi + 0.35                # spiral end angle
    rot = -2.35                           # orientation
    R = lambda t: math.exp(b * t)
    P = lambda t, k=1.0: (k * R(t) * math.cos(t + rot), k * R(t) * math.sin(t + rot))
    # silhouette = last full turn of the outer whorl (closes on itself at the aperture)
    n = 360
    sil = [P(T - 2 * math.pi + 2 * math.pi * i / n) for i in range(n + 1)]
    xs = [p[0] for p in sil]; ys = [p[1] for p in sil]
    # fit into a 330px box centred on the tile
    s = 330 / max(max(xs) - min(xs), max(ys) - min(ys))
    ox = 256 - s * (max(xs) + min(xs)) / 2
    oy = 256 - s * (max(ys) + min(ys)) / 2
    tr = lambda p: (ox + s * p[0], oy + s * p[1])
    path = lambda pts: "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in map(tr, pts))
    # flared aperture lip: bow the closing edge out in the growth direction
    e, st = tr(sil[-1]), tr(sil[0])
    f = tr(P(T + 0.4)); fx, fy = f[0] - e[0], f[1] - e[1]; fl = math.hypot(fx, fy)
    L = math.hypot(st[0] - e[0], st[1] - e[1])
    q = ((e[0] + st[0]) / 2 + fx / fl * L * 0.22, (e[1] + st[1]) / 2 + fy / fl * L * 0.22)
    silhouette = path(sil) + f" Q{q[0]:.1f},{q[1]:.1f} {st[0]:.1f},{st[1]:.1f} Z"
    inner = path([P(0.6 + (T - 2 * math.pi - 0.6) * i / 300) for i in range(301)])
    # septa: chamber walls between consecutive whorls, evenly spaced in angle
    septa = []
    t = T - 1.15                          # leave the body chamber open
    while t > 2 * math.pi + 0.9:
        a = tr(P(t)); c = tr(P(t - 2 * math.pi))
        mx, my = (a[0] + c[0]) / 2, (a[1] + c[1]) / 2
        dx, dy = c[0] - a[0], c[1] - a[1]
        L = math.hypot(dx, dy)
        # bow backwards (against growth direction)
        nx, ny = dy / L, -dx / L
        q = (mx + nx * L * 0.28, my + ny * L * 0.28)
        w = max(3.0, 7.5 * L / 120)
        septa.append(f'<path d="M{a[0]:.1f},{a[1]:.1f} Q{q[0]:.1f},{q[1]:.1f} {c[0]:.1f},{c[1]:.1f}" stroke-width="{w:.1f}"/>')
        t -= 0.48
    septa = "".join(septa)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <title>Shelly-Qt</title>
  <defs>
    <radialGradient id="bg" cx="0.5" cy="0.45" r="0.75">
      <stop offset="0" stop-color="#2a1660"/>
      <stop offset="0.55" stop-color="#140b33"/>
      <stop offset="1" stop-color="#05040e"/>
    </radialGradient>
    <linearGradient id="neon" x1="0.1" y1="0.1" x2="0.9" y2="0.9">
      <stop offset="0" stop-color="#2af6ff"/>
      <stop offset="0.5" stop-color="#8c5bff"/>
      <stop offset="1" stop-color="#ff3fc9"/>
    </linearGradient>
    <linearGradient id="body" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#2af6ff" stop-opacity="0.22"/>
      <stop offset="1" stop-color="#ff3fc9" stop-opacity="0.22"/>
    </linearGradient>
    <filter id="glow" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="10"/>
    </filter>
    <clipPath id="tile"><rect x="24" y="24" width="464" height="464" rx="104"/></clipPath>
  </defs>
  <rect x="24" y="24" width="464" height="464" rx="104" fill="url(#bg)"/>
  <g clip-path="url(#tile)" stroke="#ffffff" stroke-opacity="0.05" stroke-width="2">
    <path d="M24,120 H488 M24,216 H488 M24,312 H488 M24,408 H488 M120,24 V488 M216,24 V488 M312,24 V488 M408,24 V488"/>
  </g>
  <path d="{silhouette}" fill="url(#body)"/>
  <g fill="none" stroke="url(#neon)" stroke-linecap="round" stroke-linejoin="round">
    <g filter="url(#glow)" opacity="0.9">
      <path d="{silhouette}" stroke-width="22"/>
      <path d="{inner}" stroke-width="14"/>
    </g>
    <path d="{silhouette}" stroke-width="13"/>
    <path d="{inner}" stroke-width="9"/>
    {septa}
  </g>
  <g fill="none" stroke="#ffffff" stroke-opacity="0.75" stroke-linecap="round" stroke-linejoin="round">
    <path d="{silhouette}" stroke-width="3.5"/>
    <path d="{inner}" stroke-width="2.5"/>
  </g>
</svg>
'''

def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    svg = OUT / "shelly-qt.svg"
    svg.write_text(nautilus_svg())
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
