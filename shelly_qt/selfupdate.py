"""Self-update when running from an AppImage.

The AppImage bundles appimageupdatetool (packaging/appimage/bundle-updater.sh)
under usr/libexec/appimageupdatetool. It reads the update information embedded
in the file at $APPIMAGE (gh-releases-zsync|…), fetches the matching .zsync
from GitHub Releases and downloads only the blocks that changed.

  appimageupdatetool -j FILE   exit 1: update available, 0: up to date, other: error
  appimageupdatetool -O FILE   update FILE in place, printing "\\r<pct>% done (…)"

``SHELLY_QT_UPDATER`` (a command, may contain args) overrides the tool; tests use
it with tests/fake_appimageupdatetool.py. ``SHELLY_QT_NO_UPDATE_CHECK=1`` turns
off the quiet check at startup.
"""
from __future__ import annotations

import os
import re
import shlex
from html import escape
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit,
                               QProgressBar, QPushButton, QVBoxLayout)

TOOL_DIR = "usr/libexec/appimageupdatetool"
PROGRESS = re.compile(r"(\d+(?:\.\d+)?)% done")
NEW_FILE = re.compile(r"(?:Updated existing file|New file created:) (.+)$", re.M)

# Variables the AppImage runtime and our AppRun set. They point into the
# current mount, which goes away when this process exits.
_APPIMAGE_VARS = ("APPDIR", "APPIMAGE", "ARGV0", "OWD", "PYTHONNOUSERSITE", "QT_PLUGIN_PATH",
                  "QML_IMPORT_PATH", "QML2_IMPORT_PATH", "FONTCONFIG_PATH", "FONTCONFIG_FILE",
                  "XKB_CONFIG_ROOT", "QT_XKB_CONFIG_ROOT", "SSL_CERT_FILE")


def appimage_path() -> str | None:
    """The AppImage file this process runs from, or None."""
    p = os.environ.get("APPIMAGE")
    return p if p and os.path.isfile(p) else None


def updater_cmd() -> list[str] | None:
    """Command prefix for appimageupdatetool, or None if there is none."""
    if os.environ.get("SHELLY_QT_UPDATER"):
        return shlex.split(os.environ["SHELLY_QT_UPDATER"])
    appdir = os.environ.get("APPDIR")
    if not appdir:
        return None
    tool = Path(appdir) / TOOL_DIR / "bin/appimageupdatetool"
    return [str(tool)] if os.access(tool, os.X_OK) else None


def available() -> bool:
    """Self-update is offered only inside an AppImage that bundles the tool."""
    return appimage_path() is not None and updater_cmd() is not None


def host_env(extra: dict[str, str] | None = None) -> QProcessEnvironment:
    """The environment minus everything that points into this AppImage's mount."""
    appdir = os.environ.get("APPDIR", "")
    env = QProcessEnvironment()
    for k, v in os.environ.items():
        if k in _APPIMAGE_VARS:
            continue
        if appdir and k in ("XDG_DATA_DIRS", "PATH", "LD_LIBRARY_PATH"):
            v = ":".join(p for p in v.split(":") if p and not p.startswith(appdir))
            if not v:
                continue
        env.insert(k, v)
    for k, v in (extra or {}).items():
        env.insert(k, v)
    return env


def _tool_env() -> QProcessEnvironment:
    appdir = os.environ.get("APPDIR")
    if appdir and not os.environ.get("SHELLY_QT_UPDATER"):
        return host_env({"LD_LIBRARY_PATH": str(Path(appdir) / TOOL_DIR / "lib")})
    return host_env()


def _start(proc: QProcess, args: list[str]) -> None:
    cmd = updater_cmd() or ["appimageupdatetool"]
    proc.setProcessEnvironment(_tool_env())
    proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    proc.start(cmd[0], cmd[1:] + args)


class UpdateCheck(QObject):
    """Runs ``appimageupdatetool -j``; emits ``done(available, error_text)``."""

    done = Signal(bool, str)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.output = ""
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)

    def start(self) -> None:
        _start(self.proc, ["-j", self.path])

    def _read(self) -> None:
        self.output += bytes(self.proc.readAllStandardOutput()).decode(errors="replace")

    def _finished(self, code: int, status) -> None:
        self._read()
        if status == QProcess.ExitStatus.NormalExit and code in (0, 1):
            self.done.emit(code == 1, "")
        else:
            self.done.emit(False, self.output.strip() or f"appimageupdatetool exited with {code}")

    def _error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.done.emit(False, f"Could not start appimageupdatetool: {self.proc.errorString()}")


class UpdateDialog(QDialog):
    """Check, download (zsync delta, in place) and offer to restart."""

    def __init__(self, path: str, parent=None, *, update_known: bool = False) -> None:
        super().__init__(parent)
        self.path = path
        self.new_path = path
        self.setWindowTitle("Update Shelly-Qt")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        lay.addWidget(self.label)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.hide()   # shown once the tool prints something
        lay.addWidget(self.log, 1)
        self.buttons = QDialogButtonBox()
        self.update_btn = QPushButton("Update")
        self.restart_btn = QPushButton("Restart now")
        self.close_btn = QPushButton("Close")
        for b, role in ((self.update_btn, QDialogButtonBox.ButtonRole.AcceptRole),
                        (self.restart_btn, QDialogButtonBox.ButtonRole.AcceptRole),
                        (self.close_btn, QDialogButtonBox.ButtonRole.RejectRole)):
            self.buttons.addButton(b, role)
        self.update_btn.clicked.connect(self.download)
        self.restart_btn.clicked.connect(self.restart)
        self.close_btn.clicked.connect(self.reject)
        lay.addWidget(self.buttons)
        self.state = ""
        self._partial = ""
        self.proc = QProcess(self)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.finished.connect(self._download_finished)
        self.proc.errorOccurred.connect(self._proc_error)
        self.check = UpdateCheck(path, self)
        self.check.done.connect(self._checked)
        if update_known:
            self._checked(True, "")
        else:
            self._set("checking", f"Checking for a newer version of <b>{escape(Path(path).name)}</b>…")
            self.check.start()

    # ---- state ------------------------------------------------------------
    def _set(self, state: str, text: str) -> None:
        self.state = state
        self.label.setText(text)
        self.update_btn.setVisible(state == "available")
        self.restart_btn.setVisible(state == "updated")
        self.close_btn.setText("Later" if state in ("available", "updated") else "Close")
        self.close_btn.setEnabled(state != "downloading")
        busy = state in ("checking", "downloading")
        self.bar.setVisible(busy or state == "updated")
        if state == "checking":
            self.bar.setRange(0, 0)
        elif state == "downloading":
            self.bar.setRange(0, 1000)
            self.bar.setValue(0)
        elif state == "updated":
            self.bar.setRange(0, 1000)
            self.bar.setValue(1000)

    def _log(self, text: str) -> None:
        self.log.appendPlainText(text)
        self.log.show()

    def _checked(self, avail: bool, err: str) -> None:
        if err:
            self._log(err)
            self._set("error", "Could not check for updates.")
        elif avail:
            self._set("available", "A new version of Shelly-Qt is available. Only the parts that "
                      "changed are downloaded, and the AppImage is replaced in place:"
                      f"<br><small>{escape(self.path)}</small>")
            self.update_btn.setFocus()
        else:
            self._set("current", "Shelly-Qt is up to date.")

    # ---- download ---------------------------------------------------------
    def download(self) -> None:
        if not os.access(os.path.dirname(self.path) or ".", os.W_OK):
            self._log(f"{os.path.dirname(self.path)} is not writable.")
            self._set("error", "Can't update: the folder holding the AppImage is not writable. "
                      "Move it somewhere you own, such as ~/Applications, and try again.")
            return
        self._set("downloading", "Downloading the update…")
        self._partial = ""
        _start(self.proc, ["-O", self.path])

    def _read(self) -> None:
        text = self._partial + bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
        # progress lines end in \r (overwritten in place), messages in \n
        parts = re.split(r"[\r\n]", text)
        self._partial = parts.pop()
        for line in parts:
            self._line(line)
        m = PROGRESS.search(self._partial)
        if m:
            self._progress(float(m.group(1)))

    def _line(self, line: str) -> None:
        m = PROGRESS.search(line)
        if m:
            self._progress(float(m.group(1)))
            return
        if line.strip():
            self._log(line)
        m = NEW_FILE.search(line)
        if m:
            self.new_path = m.group(1).strip()

    def _progress(self, pct: float) -> None:
        self.bar.setValue(int(pct * 10))
        self.label.setText(f"Downloading the update… {pct:.0f}%")

    def _download_finished(self, code: int, status) -> None:
        self._read()
        if self._partial:
            self._line(self._partial)
            self._partial = ""
        if status == QProcess.ExitStatus.NormalExit and code == 0:
            self._set("updated", "Shelly-Qt was updated. Restart to use the new version.")
            self.restart_btn.setFocus()
        else:
            self._set("error", "The update failed; the current version was kept. Details:")

    def _proc_error(self, err) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._log(self.proc.errorString())
            self._set("error", "Could not start appimageupdatetool.")

    # ---- restart ----------------------------------------------------------
    def restart(self) -> None:
        if restart_into(self.new_path):
            self.accept()
            QApplication.quit()
        else:
            self._set("error", f"Could not start {escape(self.new_path)}. Start it yourself.")

    def reject(self) -> None:
        if self.state == "downloading":
            return
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.proc.kill()
        if self.check.proc.state() != QProcess.ProcessState.NotRunning:
            self.check.proc.kill()
        super().reject()


def restart_into(path: str) -> bool:
    """Start ``path`` (the updated AppImage) detached, with a clean environment."""
    proc = QProcess()
    proc.setProgram(path)
    proc.setArguments([])
    proc.setProcessEnvironment(host_env())
    owd = os.environ.get("OWD")
    if owd and os.path.isdir(owd):
        proc.setWorkingDirectory(owd)
    ok, _pid = proc.startDetached()
    return ok
