"""Desktop update dialog backed by the shared update manager."""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from src.core.update_manager import UpdateError, UpdateManager, UpdateResult


class _UpdateWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, manager: UpdateManager, *, channel: str, install: bool = False):
        super().__init__()
        self.manager = manager
        self.channel = channel
        self.install = install

    @Slot()
    def run(self) -> None:
        try:
            result = self.manager.check(channel=self.channel)
            if self.install and result.available and result.can_install:
                result = self.manager.download_update(result)
                result.message = "更新文件已下载并校验，关闭 Mozikit 后将启动安装程序。"
            self.finished.emit(result)
        except Exception as exc:  # surfaced as a user-facing dialog message
            self.failed.emit(exc)


class UpdateDialog(QDialog):
    """Check and install updates without blocking the Qt event loop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Mozikit 更新")
        self.setMinimumWidth(520)
        self.manager = UpdateManager()
        self._thread: QThread | None = None
        self._worker: _UpdateWorker | None = None
        self.install_started = False
        self.install_ready_path: str | None = None
        self.install_ready_candidate = None
        self._last_result: UpdateResult | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("更新频道"))
        self.channel = QComboBox(self)
        self.channel.addItems(["stable", "nightly"])
        self.channel.setCurrentText(self.manager.default_channel)
        layout.addWidget(self.channel)

        self.summary = QLabel("尚未检查更新。")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.details = QPlainTextEdit(self)
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(220)
        layout.addWidget(self.details)

        self.check_button = QPushButton("检查更新", self)
        self.check_button.clicked.connect(self._start_check)
        layout.addWidget(self.check_button)

        self.install_button = QPushButton("下载并安装", self)
        self.install_button.setEnabled(False)
        self.install_button.clicked.connect(self._start_install)
        layout.addWidget(self.install_button)

        buttons = QDialogButtonBox(QDialogButtonBox.Close, parent=self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _start_check(self) -> None:
        self._run_worker(install=False)

    def _start_install(self) -> None:
        if not self._last_result or not self._last_result.available:
            return
        answer = QMessageBox.question(
            self,
            "确认更新",
            "Mozikit 将下载更新并启动 Windows 安装程序。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._run_worker(install=True)

    def _run_worker(self, *, install: bool) -> None:
        if self._thread is not None:
            return
        self.check_button.setEnabled(False)
        self.install_button.setEnabled(False)
        self.summary.setText("正在检查更新，请稍候……" if not install else "正在下载并启动安装程序……")

        self._thread = QThread(self)
        self._worker = _UpdateWorker(
            self.manager, channel=self.channel.currentText(), install=install
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._worker_finished)
        self._worker.failed.connect(self._worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread_finished)
        self._thread.start()

    @Slot(object)
    def _worker_finished(self, result: UpdateResult) -> None:
        self._last_result = result
        self.summary.setText(result.message or result.status)
        self.details.setPlainText(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        self.install_button.setEnabled(result.available and result.can_install)
        if result.status == "downloaded" and result.downloaded_path and result.candidate:
            self.install_ready_path = result.downloaded_path
            self.install_ready_candidate = result.candidate
            self.install_button.setEnabled(False)
            self.summary.setText("更新文件已下载并校验，请关闭此窗口后启动安装程序。")

    @Slot(object)
    def _worker_failed(self, error: Exception) -> None:
        if isinstance(error, UpdateError):
            payload = {"error": error.to_dict()}
            message = error.message
        else:
            payload = {"error": {"code": "error", "message": str(error)}}
            message = str(error)
        self.summary.setText(f"更新失败：{message}")
        self.details.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    @Slot()
    def _thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self.check_button.setEnabled(True)
        if self._last_result:
            self.install_button.setEnabled(
                self._last_result.available and self._last_result.can_install
            )

    def closeEvent(self, event) -> None:
        if self._thread is not None and self._thread.isRunning():
            QMessageBox.information(self, "更新处理中", "请等待当前更新操作完成。")
            event.ignore()
            return
        super().closeEvent(event)


__all__ = ["UpdateDialog"]
