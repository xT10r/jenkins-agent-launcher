"""Тесты GUI-диалогов."""

from pathlib import Path

from src.gui import dialogs


class _FakeMessageBox:
    Information = object()
    Ok = object()

    instances = []

    def __init__(self, parent):
        self.parent = parent
        self.window_title = None
        self.text = None
        self.window_icon = None
        self.icon_pixmap = None
        self.exec_called = False
        _FakeMessageBox.instances.append(self)

    def setWindowTitle(self, value):
        self.window_title = value

    def setTextFormat(self, value):
        self.text_format = value

    def setText(self, value):
        self.text = value

    def setIcon(self, value):
        self.icon = value

    def setStandardButtons(self, value):
        self.buttons = value

    def setWindowIcon(self, value):
        self.window_icon = value

    def setIconPixmap(self, value):
        self.icon_pixmap = value

    def exec_(self):
        self.exec_called = True
        return 0


def test_show_about_applies_icon_when_file_exists(monkeypatch, tmp_path):
    icon_path = tmp_path / "test.ico"
    icon_path.write_bytes(b"ico")

    monkeypatch.setattr("PyQt5.QtWidgets.QMessageBox", _FakeMessageBox)

    dialogs.show_about(None, "App", "1.0", "Company", str(icon_path))

    msg = _FakeMessageBox.instances[-1]
    assert msg.window_title == "О программе"
    assert "App" in msg.text
    assert msg.window_icon is not None
    assert msg.icon_pixmap is not None
    assert msg.exec_called is True
