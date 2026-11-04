"""Process plumbing for the ``shelly`` CLI, built on QProcess so the UI never blocks."""
from __future__ import annotations

import os
import shlex
from typing import Any, Callable

from PySide6.QtCore import QObject, QProcess, Signal

from . import protocol


def shelly_bin() -> list[str]:
    """Command prefix used to launch shelly. ``SHELLY_BIN`` may contain args."""
    return shlex.split(os.environ.get("SHELLY_BIN", "shelly"))


def elevate_cmd() -> list[str]:
    """Privilege helper. ``SHELLY_ELEVATE=""`` disables elevation (useful for tests/root)."""
    value = os.environ.get("SHELLY_ELEVATE", "pkexec")
    return shlex.split(value)


def build_argv(args: list[str], privileged: bool = False) -> list[str]:
    argv = shelly_bin() + list(args) + ["--ui-mode"]
    if privileged:
        argv = elevate_cmd() + argv
    return argv


class Query(QObject):
    """One-shot command whose stdout frames are parsed when it exits.

    ``on_done(result, error)`` receives the parsed frames (via ``parse``) or an
    error string.
    """

    finished = Signal(object, object)  # result, error

    _live: set["Query"] = set()

    def __init__(self, args: list[str], parse: Callable[[str], Any] = protocol.last_data,
                 privileged: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.args = args
        self.parse = parse
        self.proc = QProcess(self)
        self.argv = build_argv(args, privileged)
        self.proc.finished.connect(self._on_finished)
        self.proc.errorOccurred.connect(self._on_error)
        self._reported = False

    def start(self) -> "Query":
        Query._live.add(self)
        self.proc.start(self.argv[0], self.argv[1:])
        return self

    def _emit(self, result: Any, error: str | None) -> None:
        if self._reported:
            return
        self._reported = True
        self.finished.emit(result, error)
        Query._live.discard(self)
        self.deleteLater()

    def _on_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self._emit(None, f"Could not start '{self.argv[0]}'. Is Shelly installed? "
                             "Set SHELLY_BIN to point at the shelly CLI.")

    def _on_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        out = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        err = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        if status != QProcess.ExitStatus.NormalExit or code != 0:
            msg = protocol.failure_message(out) or err.strip() or f"shelly exited with code {code}"
            self._emit(None, msg)
            return
        try:
            self._emit(self.parse(out), None)
        except Exception as exc:  # malformed output
            self._emit(None, f"Could not read Shelly's output: {exc}")


def query(args: list[str], on_done: Callable[[Any, str | None], None],
          parse: Callable[[str], Any] = protocol.last_data, privileged: bool = False) -> Query:
    q = Query(args, parse, privileged)
    q.finished.connect(on_done)
    return q.start()


def merged_data(text: str) -> list:
    """Concatenate every list-valued data frame (standard search streams pages)."""
    out: list = []
    for f in protocol.data_frames(text):
        if isinstance(f, list):
            out.extend(f)
    return out


class Operation(QObject):
    """A long-running, interactive transaction (install/remove/upgrade...)."""

    event = Signal(dict)      # any non-question frame
    question = Signal(dict)   # q.* frames
    log = Signal(str)         # human readable line
    progress = Signal(int, str)
    done = Signal(int)

    def __init__(self, args: list[str], privileged: bool, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.args = args
        self.privileged = privileged
        self.argv = build_argv(args, privileged)
        self.parser = protocol.FrameParser()
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.proc.readyReadStandardOutput.connect(self._read)
        self.proc.readyReadStandardError.connect(self._read_err)
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.failed_messages: list[str] = []

    @property
    def command_line(self) -> str:
        return " ".join(shlex.quote(a) for a in self.argv)

    def start(self) -> None:
        self.log.emit(f"$ {self.command_line}")
        self.proc.start(self.argv[0], self.argv[1:])

    def cancel(self) -> None:
        if self.proc.state() != QProcess.ProcessState.NotRunning:
            self.log.emit("Cancelling…")
            self.proc.kill()

    def answer(self, obj: dict) -> None:
        self.proc.write(protocol.encode_frame(obj))

    def _error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.log.emit(f"Could not start {self.argv[0]}.")
            self.done.emit(127)

    def _read_err(self) -> None:
        text = bytes(self.proc.readAllStandardError()).decode(errors="replace")
        for line in text.splitlines():
            if line.strip():
                self.log.emit(line)

    def _read(self) -> None:
        text = bytes(self.proc.readAllStandardOutput()).decode(errors="replace")
        for frame in self.parser.feed(text):
            if not isinstance(frame, dict):
                continue
            k = protocol.kind(frame)
            if k in protocol.QUESTION_KINDS:
                self.question.emit(frame)
                continue
            self.event.emit(frame)
            self._describe(k, frame)

    def _describe(self, k: str, f: dict) -> None:
        if k == "alpm.info":
            msg = f.get("Message") or f.get("EventType", "")
            cur, tot = f.get("CurrentIndex"), f.get("TotalCount")
            prefix = f"({cur}/{tot}) " if cur is not None and tot else ""
            if msg:
                self.log.emit(prefix + msg)
        elif k == "alpm.error":
            msg = f.get("ErrorMessage", "")
            fatal = f.get("Level", "Error") == "Error" and not f.get("Recoverable", False)
            if fatal:
                self.failed_messages.append(msg)
            self.log.emit(("Error: " if fatal else "Warning: ") + msg)
        elif k == "alpm.progress":
            pct = max(0, min(100, int(f.get("Percent", 0) or 0)))
            label = " ".join(x for x in (f.get("ProgressType", ""), f.get("PackageName", ""),
                                          f.get("Stage") or "") if x)
            self.progress.emit(pct, label)
        elif k in ("flatpak.progress", "appimage.progress"):
            pct = max(0, min(100, int(f.get("Percentage", 0) or 0)))
            self.progress.emit(pct, f.get("Status") or "")
        elif k:
            msg = f.get("Message") or f.get("ErrorMessage")
            if msg:
                self.log.emit(msg)

    def _finished(self, code: int, status: QProcess.ExitStatus) -> None:
        self._read()
        if status != QProcess.ExitStatus.NormalExit:
            code = code or 1
        if self.privileged and code in (126, 127):
            self.log.emit("Authorization was cancelled or the privilege helper is unavailable.")
        self.done.emit(code)
