"""Тесты GUI-диалогов."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QTextEdit

from src.gui import dialogs


_APP = None


def _ensure_qapplication():
    global _APP
    _APP = QApplication.instance() or _APP or QApplication([])
    return _APP


def test_show_about_applies_icon_when_file_exists():
    _ensure_qapplication()

    icon_path = Path("assets/jenkins.ico")

    shown = {}

    def capture_exec(self):
        shown["dialog"] = self
        return 0

    from PyQt5.QtWidgets import QDialog

    original_exec = QDialog.exec_
    QDialog.exec_ = capture_exec
    try:
        dialogs.show_about(None, "App", "1.0", "Company", str(icon_path))
    finally:
        QDialog.exec_ = original_exec

    dialog = shown["dialog"]
    icon_labels = [label for label in dialog.findChildren(QLabel) if label.pixmap()]
    assert dialog.windowTitle() == "О программе"
    assert dialog.windowIcon().isNull() is False
    assert dialog.size().width() == 960
    assert dialog.size().height() == 880
    assert dialog.findChildren(QTextEdit) == []
    assert icon_labels
    assert icon_labels[0].width() == 112
    assert icon_labels[0].pixmap().isNull() is False
