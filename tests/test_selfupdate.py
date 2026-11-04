"""AppImage self-update, driven against tests/fake_appimageupdatetool.py."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from shelly_qt import selfupdate  # noqa: E402
from test_gui import app, wait_until  # noqa: E402,F401

FAKE = Path(__file__).with_name("fake_appimageupdatetool.py")


@pytest.fixture
def appimage(tmp_path, monkeypatch):
    f = tmp_path / "Shelly-Qt-0.1-x86_64.AppImage"
    f.write_text("old\n")
    f.chmod(0o755)
    monkeypatch.setenv("APPIMAGE", str(f))
    monkeypatch.setenv("SHELLY_QT_UPDATER", f"{sys.executable} {FAKE}")
    monkeypatch.setenv("SHELLY_QT_NO_UPDATE_CHECK", "1")
    return f


def test_not_available_outside_appimage(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("SHELLY_QT_UPDATER", raising=False)
    monkeypatch.delenv("APPDIR", raising=False)
    assert not selfupdate.available()


def test_bundled_tool_is_found(tmp_path, monkeypatch):
    tool = tmp_path / "usr/libexec/appimageupdatetool/bin/appimageupdatetool"
    tool.parent.mkdir(parents=True)
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.delenv("SHELLY_QT_UPDATER", raising=False)
    monkeypatch.setenv("APPDIR", str(tmp_path))
    assert selfupdate.updater_cmd() == [str(tool)]


def test_host_env_drops_mount_paths(monkeypatch):
    monkeypatch.setenv("APPDIR", "/tmp/.mount_ShellyX")
    monkeypatch.setenv("QT_PLUGIN_PATH", "/tmp/.mount_ShellyX/usr/lib/qt6/plugins")
    monkeypatch.setenv("XDG_DATA_DIRS", "/tmp/.mount_ShellyX/usr/share:/usr/share")
    env = selfupdate.host_env()
    assert not env.contains("APPDIR") and not env.contains("QT_PLUGIN_PATH")
    assert env.value("XDG_DATA_DIRS") == "/usr/share"


def test_check_and_update_in_place(appimage):
    d = selfupdate.UpdateDialog(str(appimage))
    wait_until(lambda: d.state != "checking")
    assert d.state == "available" and d.update_btn.isVisible() is not None
    d.download()
    wait_until(lambda: d.state != "downloading")
    assert d.state == "updated", d.log.toPlainText()
    assert appimage.read_text() == "old\nupdated\n"
    assert d.new_path == str(appimage)
    assert d.bar.value() == 1000
    assert "Update successful" in d.log.toPlainText()
    d.close()


def test_restart_starts_new_file(appimage, monkeypatch):
    started = []
    monkeypatch.setattr(selfupdate, "restart_into", lambda p: started.append(p) or True)
    monkeypatch.setattr(selfupdate.QApplication, "quit", staticmethod(lambda: None))
    d = selfupdate.UpdateDialog(str(appimage), update_known=True)
    d.download()
    wait_until(lambda: d.state != "downloading")
    d.restart()
    assert started == [str(appimage)]


@pytest.mark.parametrize("mode,state", [("current", "current"), ("error", "error")])
def test_check_outcomes(appimage, monkeypatch, mode, state):
    monkeypatch.setenv("FAKE_UPDATE", mode)
    d = selfupdate.UpdateDialog(str(appimage))
    wait_until(lambda: d.state != "checking")
    assert d.state == state
    d.close()


def test_failed_update_keeps_file(appimage, monkeypatch):
    monkeypatch.setenv("FAKE_UPDATE", "fail")
    d = selfupdate.UpdateDialog(str(appimage), update_known=True)
    d.download()
    wait_until(lambda: d.state != "downloading")
    assert d.state == "error"
    assert "Update failed!" in d.log.toPlainText()
    assert appimage.read_text() == "old\n"
    d.close()


def test_main_window_quiet_check_shows_button(appimage, monkeypatch):
    from shelly_qt.app import MainWindow
    w = MainWindow()
    assert w.update_action.isVisible()
    w._quiet_update_check()
    wait_until(lambda: not w.update_button.isHidden())
    w.close()


def test_main_window_hides_action_outside_appimage(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delenv("SHELLY_QT_UPDATER", raising=False)
    from shelly_qt.app import MainWindow
    w = MainWindow()
    assert not w.update_action.isVisible()
    w.close()
