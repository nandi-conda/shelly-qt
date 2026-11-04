"""Files and links passed on the command line ("Open with Shelly-Qt")."""
from shelly_qt.openfile import classify, targets_from_argv

REF = """[Flatpak Ref]
Name=org.kde.krita
Branch=stable
Title=Krita
IsRuntime=false
Url=https://dl.flathub.org/repo/
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
Comment=Digital painting
GPGKey=mQINBFlD2sABEADsiUZUO
"""


def test_flatpakref_is_parsed(tmp_path):
    p = tmp_path / "org.kde.krita.flatpakref"
    p.write_text(REF)
    t = classify(str(p))
    assert t.kind == "flatpakref" and t.value == str(p)
    assert t.info["Name"] == "org.kde.krita" and t.name == "Krita"
    assert "GPGKey" not in t.info


def test_file_uri_and_relative_paths(tmp_path):
    p = tmp_path / "my app.flatpakref"
    p.write_text(REF)
    assert classify("file://" + str(p).replace(" ", "%20")).value == str(p)
    assert classify("my app.flatpakref", cwd=str(tmp_path)).value == str(p)


def test_other_kinds(tmp_path):
    assert classify(str(tmp_path / "a.flatpak")).kind == "bundle"
    assert classify(str(tmp_path / "a.flatpakrepo")).kind == "flatpakrepo"
    assert classify(str(tmp_path / "Obsidian.AppImage")).kind == "appimage"
    assert classify(str(tmp_path / "zed-1.0-1-x86_64.pkg.tar.zst")).kind == "pkg"
    assert classify(str(tmp_path / "notes.txt")).kind == "unknown"


def test_links():
    assert classify("appstream://org.kde.krita").value == "org.kde.krita"
    t = classify("flatpak+https://dl.flathub.org/repo/appstream/org.gimp.GIMP.flatpakref")
    assert (t.kind, t.value) == ("appid", "org.gimp.GIMP")
    assert [t.kind for t in targets_from_argv(["--style", "appstream://x.y"])] == ["appid"]
