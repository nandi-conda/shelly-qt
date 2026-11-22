import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from shelly_qt import kdecolors  # noqa: E402

app = QApplication.instance() or QApplication([])

HEX_SCHEME = """\
[Colors:Button]
BackgroundNormal=#231e25
ForegroundNormal=#ede2ee
[Colors:Window]
BackgroundNormal=#1d181e
ForegroundNormal=#ede2ee
[Colors:View]
BackgroundNormal=#0d0a0e
ForegroundNormal=237,226,238
[Colors:Selection]
BackgroundNormal=255,170,255
[General]
ColorScheme=Dark
"""


def colors_from(tmp_path, text):
    f = tmp_path / "kdeglobals"
    f.write_text(text)
    return kdecolors.read_colors([f])


def test_parse_color_accepts_rgb_and_hex():
    assert kdecolors.parse_color("1,2,3").getRgb()[:3] == (1, 2, 3)
    assert kdecolors.parse_color("#0d0a0e").name() == "#0d0a0e"
    assert kdecolors.parse_color("nonsense") is None


def test_fallback_only_when_qt_cannot_read_scheme(tmp_path):
    assert kdecolors.qt_cannot_read(colors_from(tmp_path, HEX_SCHEME))
    rgb = HEX_SCHEME.replace("#231e25", "35,30,37")
    assert not kdecolors.qt_cannot_read(colors_from(tmp_path, rgb))
    assert not kdecolors.qt_cannot_read(colors_from(tmp_path, "[General]\nColorScheme=x\n"))


def test_palette_follows_scheme_with_mixed_formats(tmp_path):
    pal = kdecolors.build_palette(colors_from(tmp_path, HEX_SCHEME))
    assert pal.color(QPalette.ColorRole.Window).name() == "#1d181e"
    assert pal.color(QPalette.ColorRole.Base).name() == "#0d0a0e"
    assert pal.color(QPalette.ColorRole.Text).name() == "#ede2ee"
    assert pal.color(QPalette.ColorRole.Highlight).name() == "#ffaaff"


def test_earlier_kdeglobals_wins(tmp_path):
    high, low = tmp_path / "a", tmp_path / "b"
    high.write_text("[Colors:Button]\nBackgroundNormal=#111111\n")
    low.write_text("[Colors:Button]\nBackgroundNormal=#222222\n[Colors:Window]\nBackgroundNormal=#333333\n")
    colors = kdecolors.read_colors([high, low])
    assert colors[("Button", "BackgroundNormal")] == "#111111"
    assert colors[("Window", "BackgroundNormal")] == "#333333"
