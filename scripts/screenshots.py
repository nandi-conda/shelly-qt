"""Render screenshots/ using whatever SHELLY_BIN points at (the justfile uses the fake CLI)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])
app.setStyle("Fusion")

from shelly_qt.app import MainWindow  # noqa: E402
from shelly_qt.dialogs import TransactionDialog  # noqa: E402

out = Path(__file__).resolve().parents[1] / "screenshots"
out.mkdir(exist_ok=True)


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


w = MainWindow()
w.show()
wait(1500)
w.pages[0].table.view.selectRow(0)
wait(800)
w.grab().save(str(out / "browse.png"))
w.nav.setCurrentRow(2)
wait(800)
w.grab().save(str(out / "updates.png"))
w.nav.setCurrentRow(3)
w.pages[3].query.setText("ya")
w.pages[3].search()
wait(800)
w.pages[3].results.view.selectRow(0)
wait(200)
w.grab().save(str(out / "aur.png"))
w.search_all("zed")
wait(1000)
w.search_page.table.view.selectRow(0)
wait(600)
w.grab().save(str(out / "search.png"))
d = TransactionDialog({
    "$kind": "q.transaction", "QuestionId": "t", "Action": "install",
    "QuestionText": "Proceed with installation?",
    "Packages": [
        {"Name": "zed", "Version": "0.165.4-1", "Repository": "extra", "Role": "target",
         "DownloadSize": 31000000, "InstalledSize": 90000000},
        {"Name": "vulkan-icd-loader", "Version": "1.3.295-1", "Repository": "extra",
         "Role": "dependency", "DownloadSize": 150000, "InstalledSize": 600000},
    ],
    "TotalDownloadSize": 31150000, "TotalInstalledSize": 90600000, "NetInstalledSize": 90600000,
})
d.show()
wait(200)
d.grab().save(str(out / "transaction.png"))
print(f"wrote screenshots to {out}")
