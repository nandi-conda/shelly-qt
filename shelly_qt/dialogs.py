"""Dialogs that answer the CLI's interactive questions, and the operation runner."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from . import protocol
from .cli import Operation


def _mono() -> QFont:
    f = QFont("monospace")
    f.setStyleHint(QFont.StyleHint.Monospace)
    return f


class TransactionDialog(QDialog):
    """``q.transaction``: review packages before the transaction commits."""

    def __init__(self, q: dict, parent=None) -> None:
        super().__init__(parent)
        action = q.get("Action", "") or "transaction"
        self.setWindowTitle(f"Confirm {action}")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(q.get("QuestionText") or f"Proceed with {action}?"))

        pkgs = q.get("Packages") or []
        table = QTableWidget(len(pkgs), 6)
        table.setHorizontalHeaderLabels(["Package", "Version", "Source", "Role", "Download", "Installed"])
        for r, p in enumerate(pkgs):
            vals = [p.get("Name", ""), p.get("Version") or "",
                    p.get("Repository") or p.get("Source", ""), p.get("Role", ""),
                    protocol.human_size(p.get("DownloadSize")), protocol.human_size(p.get("InstalledSize"))]
            for c, v in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(str(v)))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().hide()
        lay.addWidget(table)

        totals = []
        if q.get("TotalDownloadSize") is not None:
            totals.append(f"Download: {protocol.human_size(q['TotalDownloadSize'])}")
        if q.get("TotalInstalledSize") is not None:
            totals.append(f"Installed: {protocol.human_size(q['TotalInstalledSize'])}")
        if q.get("NetInstalledSize") is not None:
            totals.append(f"Net change: {protocol.human_size(q['NetInstalledSize'])}")
        migrations = q.get("Migrations") or []
        if migrations:
            totals.append(f"{len(migrations)} file migration(s)")
        if totals:
            lay.addWidget(QLabel("   ·   ".join(totals)))

        bb = QDialogButtonBox()
        bb.addButton("Proceed", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton(QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SelectDialog(QDialog):
    """``q.optdeps`` (many) and ``q.provider`` (one)."""

    def __init__(self, q: dict, many: bool, parent=None) -> None:
        super().__init__(parent)
        self.many = many
        self.setWindowTitle("Optional dependencies" if many else "Choose a provider")
        self.resize(560, 420)
        lay = QVBoxLayout(self)
        prompt = q.get("QuestionText") or ""
        if not many and q.get("DependencyName"):
            prompt = f"Several packages provide {q['DependencyName']}. Choose one:"
        lay.addWidget(QLabel(prompt or "Select:"))
        self.options = q.get("Options") or []
        self.list = QListWidget()
        self.group = QButtonGroup(self)
        for i, o in enumerate(self.options):
            text = o.get("Name", "")
            if o.get("Description"):
                text += f" — {o['Description']}"
            if o.get("IsInstalled"):
                text += "  [installed]"
            item = QListWidgetItem()
            self.list.addItem(item)
            if many:
                item.setText(text)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if o.get("IsSelected") else Qt.CheckState.Unchecked)
            else:
                rb = QRadioButton(text)
                rb.setChecked(i == 0 or bool(o.get("IsSelected")))
                self.group.addButton(rb, i)
                self.list.setItemWidget(item, rb)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def selected_indices(self) -> list[int]:
        return [self.options[i].get("Index", i) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def selected_index(self) -> int:
        i = max(self.group.checkedId(), 0)
        return self.options[i].get("Index", i) if self.options else 0


class PkgbuildDialog(QDialog):
    """``q.pkgbuilddiff``: review an AUR PKGBUILD (and its diff) before building."""

    def __init__(self, q: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Review PKGBUILD — {q.get('PackageName', '')}")
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        warnings = q.get("Warnings") or []
        if warnings:
            w = QLabel("<b>Warnings:</b><br>" + "<br>".join(
                f"[{x.get('Severity', '')}] {x.get('Message', '')} <code>{x.get('MatchedLine', '')}</code>"
                for x in warnings))
            w.setWordWrap(True)
            w.setStyleSheet("color: #b45309;")
            lay.addWidget(w)

        tabs = QTabWidget()
        diff = QTextEdit()
        diff.setReadOnly(True)
        diff.setFont(_mono())
        lines = q.get("DiffLines") or []
        if lines:
            cur = diff.textCursor()
            for line in lines:
                fmt = QTextCharFormat()
                if line.startswith("+"):
                    fmt.setForeground(QColor("#15803d"))
                elif line.startswith("-"):
                    fmt.setForeground(QColor("#b91c1c"))
                cur.insertText(line + "\n", fmt)
            tabs.addTab(diff, "Diff")
        new = QPlainTextEdit(q.get("NewPkgbuild", ""))
        new.setReadOnly(True)
        new.setFont(_mono())
        tabs.addTab(new, "PKGBUILD")
        if q.get("OldPkgbuild"):
            old = QPlainTextEdit(q["OldPkgbuild"])
            old.setReadOnly(True)
            old.setFont(_mono())
            tabs.addTab(old, "Previous")
        for name, content in (q.get("SourceFiles") or {}).items():
            t = QPlainTextEdit(content)
            t.setReadOnly(True)
            t.setFont(_mono())
            tabs.addTab(t, name)
        lay.addWidget(tabs)
        bb = QDialogButtonBox()
        bb.addButton("Build and install", QDialogButtonBox.ButtonRole.AcceptRole)
        bb.addButton("Abort", QDialogButtonBox.ButtonRole.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def ask(q: dict, parent=None) -> dict:
    """Show the right dialog for question ``q`` and return the answer frame."""
    from PySide6.QtWidgets import QMessageBox

    k = protocol.kind(q)
    qid = q.get("QuestionId", "")
    if k == "q.transaction":
        return protocol.answer_transaction(qid, TransactionDialog(q, parent).exec() == QDialog.DialogCode.Accepted)
    if k == "q.optdeps":
        d = SelectDialog(q, True, parent)
        return protocol.answer_optdeps(qid, d.selected_indices() if d.exec() else [])
    if k == "q.provider":
        d = SelectDialog(q, False, parent)
        d.exec()
        return protocol.answer_provider(qid, d.selected_index())
    if k == "q.pkgbuilddiff":
        return protocol.answer_pkgbuild(qid, PkgbuildDialog(q, parent).exec() == QDialog.DialogCode.Accepted)
    # q.yesno and anything unknown
    text = q.get("QuestionText") or "Continue?"
    args = q.get("Arguments") or []
    if args:
        text += "\n\n" + "\n".join(args)
    res = QMessageBox.question(parent, "Shelly", text,
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return protocol.answer_yesno(qid, res == QMessageBox.StandardButton.Yes)


class OperationDialog(QDialog):
    """Runs an :class:`Operation`, streams its log/progress and answers questions."""

    completed = Signal(int)

    def __init__(self, title: str, args: list[str], privileged: bool, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 460)
        self.op = Operation(args, privileged, self)
        lay = QVBoxLayout(self)
        self.status = QLabel(title + "…")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setFont(_mono())
        lay.addWidget(self.logview)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_btn = QPushButton("Cancel")
        self.close_btn = QPushButton("Close")
        self.close_btn.setEnabled(False)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.close_btn)
        lay.addLayout(row)

        self.cancel_btn.clicked.connect(self.op.cancel)
        self.close_btn.clicked.connect(self.accept)
        self.op.log.connect(self._log)
        self.op.progress.connect(self._progress)
        self.op.question.connect(self._question)
        self.op.done.connect(self._done)
        self.exit_code: int | None = None

    def run(self) -> None:
        self.show()
        self.op.start()

    def _log(self, line: str) -> None:
        self.logview.appendPlainText(line)
        self.logview.moveCursor(QTextCursor.MoveOperation.End)

    def _progress(self, pct: int, label: str) -> None:
        self.bar.setRange(0, 100)
        self.bar.setValue(pct)
        if label:
            self.status.setText(label)

    def _question(self, q: dict) -> None:
        self.op.answer(ask(q, self))

    def _done(self, code: int) -> None:
        if self.exit_code is not None:
            return
        self.exit_code = code
        self.bar.setRange(0, 100)
        self.bar.setValue(100 if code == 0 else self.bar.value())
        if code == 0:
            self.status.setText("Finished successfully.")
        else:
            detail = "\n".join(self.op.failed_messages) or f"Shelly exited with code {code}."
            self.status.setText("Failed: " + detail)
            self.status.setStyleSheet("color: #b91c1c;")
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.close_btn.setDefault(True)
        self.completed.emit(code)

    def reject(self) -> None:  # Esc / window close while running
        if self.exit_code is None:
            self.op.cancel()
            return
        super().reject()
