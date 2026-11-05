"""Dialogs that answer the CLI's interactive questions, and the operation runner."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton,
    QRadioButton, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from . import ansi, cli, conflicts, protocol
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
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
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


def _exec(d: QDialog) -> int:
    """Run a question dialog modal to its operation window only, so the main
    window (and any other running operation) stays usable meanwhile."""
    d.setWindowModality(Qt.WindowModality.WindowModal)
    return d.exec()


def ask(q: dict, parent=None) -> dict:
    """Show the right dialog for question ``q`` and return the answer frame."""
    from PySide6.QtWidgets import QMessageBox

    k = protocol.kind(q)
    qid = q.get("QuestionId", "")
    if k == "q.transaction":
        return protocol.answer_transaction(qid, _exec(TransactionDialog(q, parent)) == QDialog.DialogCode.Accepted)
    if k == "q.optdeps":
        d = SelectDialog(q, True, parent)
        return protocol.answer_optdeps(qid, d.selected_indices() if _exec(d) else [])
    if k == "q.provider":
        d = SelectDialog(q, False, parent)
        _exec(d)
        return protocol.answer_provider(qid, d.selected_index())
    if k == "q.pkgbuilddiff":
        return protocol.answer_pkgbuild(qid, _exec(PkgbuildDialog(q, parent)) == QDialog.DialogCode.Accepted)
    # q.yesno and anything unknown
    text = q.get("QuestionText") or "Continue?"
    args = q.get("Arguments") or []
    if args:
        text += "\n\n" + "\n".join(args)
    box = QMessageBox(QMessageBox.Icon.Question, "Shelly", text,
                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, parent)
    return protocol.answer_yesno(qid, _exec(box) == QMessageBox.StandardButton.Yes)


# Banner palettes: (accent/border, tint, title text), for dark and light themes.
_TONES = {
    "error": {"dark": ("#e88388", "#3a2a2d", "#f4b6b9"), "light": ("#d9534f", "#fbeeee", "#9f2f2b")},
    "info": {"dark": ("#d8b26a", "#363126", "#ecd5a3"), "light": ("#c98a1b", "#fdf6e7", "#7a5410")},
}
_ICONS = {"error": "dialog-error", "info": "dialog-information"}
_BENIGN = ("already installed", "is already up to date", "nothing to do", "already up-to-date")


def split_error(text: str) -> tuple[str, str]:
    """Split a CLI error into a one-paragraph summary and the technical rest."""
    text = text.strip()
    head, _, rest = text.partition("\n\n")
    lines = head.splitlines()
    summary, extra = (lines[0] if lines else text), lines[1:]
    detail = "\n".join(extra + ([rest] if rest else [])).strip()
    return summary, detail


class Banner(QFrame):
    """A soft, theme-aware notice box: icon, a readable title/summary and muted details."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("banner")
        self.tone = ""
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(12)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel()
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        df = self.detail.font()
        df.setPointSizeF(max(7.0, df.pointSizeF() * 0.9))
        self.detail.setFont(df)
        for w in (self.title, self.summary, self.detail):
            col.addWidget(w)
        row.addLayout(col, 1)
        self.hide()

    def show_message(self, tone: str, title: str, summary: str, detail: str = "") -> None:
        self.tone = tone
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        accent, tint, title_fg = _TONES[tone]["dark" if dark else "light"]
        text = self.palette().color(QPalette.ColorRole.WindowText)
        muted = QColor(text)
        muted.setAlphaF(0.6)
        self.setStyleSheet(
            f"QFrame#banner {{ background: {tint}; border: 1px solid {accent}55;"
            f" border-left: 4px solid {accent}; border-radius: 6px; }}"
            f"QFrame#banner QLabel {{ background: transparent; border: none; }}")
        self.title.setStyleSheet(f"color: {title_fg};")
        self.summary.setStyleSheet(f"color: {text.name()};")
        self.detail.setStyleSheet(f"color: {muted.name(QColor.NameFormat.HexArgb)};")
        icon = QIcon.fromTheme(_ICONS[tone])
        self.icon.setPixmap(icon.pixmap(24, 24) if not icon.isNull() else
                            self.style().standardIcon(
                                self.style().StandardPixmap.SP_MessageBoxCritical if tone == "error"
                                else self.style().StandardPixmap.SP_MessageBoxInformation).pixmap(24, 24))
        self.title.setText(title)
        self.summary.setText(summary)
        self.summary.setVisible(bool(summary))
        self.detail.setText(detail)
        self.detail.setVisible(bool(detail))
        self.show()


def ansi_format(a: "ansi.Attrs", pal: QPalette) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fg = QColor(*a.fg) if a.fg else pal.color(QPalette.ColorRole.Text)
    bg = QColor(*a.bg) if a.bg else None
    if a.inverse:
        fg, bg = (bg or pal.color(QPalette.ColorRole.Base)), fg
    if a.dim:
        fg.setAlphaF(0.6)
    if a.hidden:
        fg = bg or pal.color(QPalette.ColorRole.Base)
    if a.fg or a.inverse or a.dim or a.hidden:
        fmt.setForeground(fg)
    if bg is not None:
        fmt.setBackground(bg)
    if a.bold:
        fmt.setFontWeight(QFont.Weight.Bold)
    if a.italic:
        fmt.setFontItalic(True)
    if a.underline:
        fmt.setFontUnderline(True)
    return fmt


class OperationDialog(QDialog):
    """Runs an :class:`Operation`, streams its log/progress and answers questions.

    It is a standalone top-level window (no parent), so it gets its own
    taskbar entry, can sit behind or beside the main window, and never blocks
    it. The caller keeps a reference to it while it is open.
    """

    completed = Signal(int)

    def __init__(self, title: str, args: list[str], privileged: bool, parent=None) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle(title)
        self.setModal(False)
        self.resize(760, 460)
        self.op = Operation(args, privileged, self)
        lay = QVBoxLayout(self)
        self.status = QLabel(title + "…")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        lay.addWidget(self.bar)
        self.banner = Banner()
        lay.addWidget(self.banner)
        self.fix = FixPanel(self)
        self.fix.chosen.connect(self._apply_fix)
        lay.addWidget(self.fix)
        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setFont(_mono())
        self._ansi = ansi.Attrs()
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
        self.args = list(args)
        self.privileged = privileged
        # Set by the main window: run_follow_up(title, args, privileged, then) starts
        # another operation; ``then`` (or None) runs after it succeeds.
        self.run_follow_up = None

    def run(self) -> None:
        self.show()
        self.op.start()

    def _log(self, line: str) -> None:
        for text in line.split("\n"):
            self._log_line(text)
        self.logview.moveCursor(QTextCursor.MoveOperation.End)

    def _log_line(self, line: str) -> None:
        """Append one console line, rendering its ANSI colours and styles."""
        runs, self._ansi = ansi.parse(line, self._ansi)
        cur = QTextCursor(self.logview.document())
        cur.movePosition(QTextCursor.MoveOperation.End)
        if not self.logview.document().isEmpty():
            cur.insertBlock()
        for text, a in runs:
            cur.insertText(text, ansi_format(a, self.logview.palette()))

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
            msgs = self.op.failed_messages or [f"Shelly exited with code {code}."]
            summary, detail = split_error(msgs[0])
            more = "\n\n".join(m.strip() for m in msgs[1:])
            detail = "\n\n".join(x for x in (detail, more) if x)
            benign = any(b in summary.lower() for b in _BENIGN)
            if benign:
                self.status.setText("Nothing to do.")
                self.banner.show_message("info", "Nothing changed", summary, detail)
            else:
                self.status.setText("Failed.")
                self.banner.show_message("error", "This didn't work", summary, detail)
                self._offer_fixes()
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self.close_btn.setDefault(True)
        self.completed.emit(code)

    # ---- resolving "would remove a package that X requires" -------------
    def _offer_fixes(self) -> None:
        req = conflicts.install_request(self.args)
        blockers = conflicts.find_blockers(self.op.error_messages + self.op.failed_messages)
        if not req or not blockers or self.run_follow_up is None:
            return
        self.fix.start(req, blockers)
        if req.backend != "aur":
            self.fix.finish({})
            return
        # Look up the targets (for their package base) and every dependent's
        # possible replacements, then pick one per dependent.
        found: dict[str, list] = {}
        names = list(dict.fromkeys(req.targets + [b.dependent for b in blockers]))

        def got(name, res, err):
            found[name] = res if isinstance(res, list) and not err else []
            if len(found) < len(names):
                return
            targets = [r for t in req.targets for r in found.get(t, []) if isinstance(r, dict)]
            picks = {}
            for b in blockers:
                cands = [r for r in found.get(b.dependent, []) if isinstance(r, dict)]
                pick = conflicts.pick_replacement(b, req, targets, cands)
                if pick:
                    picks[b.dependent] = pick
            self.fix.finish(picks)

        for n in names:
            cli.query(["search", "aur", n], lambda r, e, n=n: got(n, r, e),
                      parse=lambda t: protocol.last_data(t, []))

    def _apply_fix(self, title: str, args: list, then_retry: bool) -> None:
        if self.run_follow_up is None:
            return
        retry = (lambda: self.run_follow_up(self.windowTitle(), self.args, self.privileged, None)) \
            if then_retry else None
        self.run_follow_up(title, args, self.privileged, retry)
        self.accept()

    def reject(self) -> None:  # Esc / window close while running
        if self.exit_code is None:
            self.op.cancel()
            return
        super().reject()


class FixPanel(QFrame):
    """Offers ways past install blockers: replace dependents together, or remove them first."""

    chosen = Signal(str, list, bool)  # title, args, retry original afterwards

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("fixpanel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.text)
        self.row = QHBoxLayout()
        self.row.addStretch()
        lay.addLayout(self.row)
        self.buttons: list[QPushButton] = []
        self.req: conflicts.InstallRequest | None = None
        self.blockers: list[conflicts.Blocker] = []
        self.hide()

    def start(self, req: "conflicts.InstallRequest", blockers: list) -> None:
        self.req, self.blockers = req, blockers
        self.text.setText("Looking for a way to resolve this…")
        self.show()

    def _button(self, label: str, title: str, args: list, retry: bool, primary=False) -> None:
        b = QPushButton(label)
        b.setDefault(primary)
        b.clicked.connect(lambda: self.chosen.emit(title, args, retry))
        self.row.addWidget(b)
        self.buttons.append(b)

    def finish(self, picks: dict) -> None:
        from html import escape as h
        req, blockers = self.req, self.blockers
        deps = list(dict.fromkeys(b.dependent for b in blockers))
        lines = [f"<b>{h(b.dependent)}</b> needs <code>{h(b.dependency)}</code>, which installing "
                 f"{h(', '.join(req.targets))} would replace." for b in blockers]
        what = ", ".join(req.targets)
        if picks and all(d in picks for d in deps):
            repl = [picks[d]["Name"] for d in deps]
            pairs = ", ".join(f"<b>{h(picks[d]['Name'])}</b> {h(picks[d].get('Version') or '')} "
                              f"in place of {h(d)}" for d in deps)
            lines.append(f"Install them together: {pairs}. It comes from the same source, so the "
                         "versions match, and the old package is replaced in the same step.")
            self._button(f"Install with {', '.join(repl)}",
                         f"Installing {what} with {', '.join(repl)}", req.args(repl), False, True)
        else:
            lines.append("No matching replacement was found from the same source.")
        lines.append(f"Or remove {h(', '.join(deps))} first and install {h(what)} again "
                     "(you can reinstall a compatible version afterwards).")
        self._button(f"Remove {', '.join(deps)} and retry", f"Removing {', '.join(deps)}",
                     conflicts.removal_args(blockers), True)
        self.text.setText("<br>".join(lines))
