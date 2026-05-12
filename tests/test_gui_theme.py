"""Проверки унификации светлой и тёмной темы GUI."""

from src.gui.main_window import FILETIME_UNIX_EPOCH_OFFSET_SECONDS, MainWindow


def _build_window():
    return MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
    )


def _snapshot(win):
    widgets = [type(widget).__name__ for widget in win._win.findChildren(type(win._btn_start))]
    widgets += [type(widget).__name__ for widget in win._win.findChildren(type(win._log_view))]
    widgets += [type(widget).__name__ for widget in win._win.findChildren(type(win._lbl_status))]
    return {
        "style": win._app.style().objectName(),
        "window_color": win._app.palette().color(win._app.palette().Window).name(),
        "widgets": widgets,
    }


def test_theme_switch_keeps_same_qt_style_and_widget_structure(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = _build_window()
    before = _snapshot(win)

    try:
        win._toggle_theme()
        after = _snapshot(win)
    finally:
        win._process_timer.stop()
        win._tray.hide()
        win.hide_window()

    assert before["style"] == "fusion"
    assert after["style"] == "fusion"
    assert before["widgets"] == after["widgets"]
    assert before["window_color"] != after["window_color"]


def test_status_updates_button_and_menu_state(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(MainWindow, "_is_pid_running", staticmethod(lambda pid: pid in {111, 222, 1234}))
    monkeypatch.setattr(MainWindow, "_format_process_memory", lambda self, pid: f"{pid} MB" if pid else "0 MB")
    monkeypatch.setattr(MainWindow, "_format_process_uptime", lambda self, pid: f"{pid}s" if pid else "-")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
        launcher_pid=111,
        parent_pid=222,
    )

    try:
        win.set_status("Работает", 1234)
        assert win._btn_start.isEnabled() is False
        assert win._btn_restart.isEnabled() is True
        assert win._btn_stop.isEnabled() is True
        assert win._act_start.isEnabled() is False
        assert win._act_restart.isEnabled() is True
        assert win._act_stop.isEnabled() is True
        assert win._process_fields["parent"]["status"].text() == "[OK]"
        assert win._process_fields["parent"]["pid"].text() == "222"
        assert win._process_fields["parent"]["ram"].text() == "222 MB"
        assert win._process_fields["parent"]["uptime"].text() == "222s"
        assert win._process_fields["launcher"]["status"].text() == "[OK]"
        assert win._process_fields["launcher"]["pid"].text() == "111"
        assert win._process_fields["launcher"]["ram"].text() == "111 MB"
        assert win._process_fields["launcher"]["uptime"].text() == "111s"
        assert win._process_fields["java"]["status"].text() == "[OK]"
        assert win._process_fields["java"]["pid"].text() == "1234"
        assert win._process_fields["java"]["ram"].text() == "1234 MB"
        assert win._process_fields["java"]["uptime"].text() == "1234s"

        win.set_status("Остановлен", 0)
        assert win._btn_start.isEnabled() is True
        assert win._btn_restart.isEnabled() is False
        assert win._btn_stop.isEnabled() is False
        assert win._act_start.isEnabled() is True
        assert win._act_restart.isEnabled() is False
        assert win._act_stop.isEnabled() is False
        assert win._process_fields["parent"]["status"].text() == "[OK]"
        assert win._process_fields["launcher"]["status"].text() == "[OK]"
        assert win._process_fields["java"]["status"].text() == "[ERR]"
        assert win._process_fields["java"]["pid"].text() == "-"
        assert win._process_fields["java"]["ram"].text() == "0 MB"
        assert win._process_fields["java"]["uptime"].text() == "-"
    finally:
        win._process_timer.stop()
        win._tray.hide()
        win.hide_window()


def test_start_minimized_uses_show_minimized(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
        start_minimized=True,
    )

    try:
        calls = []
        win._tray._available = False
        win._win.show = lambda: calls.append("show")
        win._win.showMinimized = lambda: calls.append("minimized")
        win._show_initial_window()
        assert calls == ["minimized"]
    finally:
        win._process_timer.stop()
        win._tray.hide()
        win.hide_window()


def test_start_minimized_uses_tray_hide_when_tray_available(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
        start_minimized=True,
    )

    try:
        calls = []
        win._tray._available = True
        monkeypatch.setattr(type(win._tray), "is_visible", property(lambda self: True))
        win._win.show = lambda: calls.append("show")
        monkeypatch.setattr("src.gui.main_window.QTimer.singleShot", lambda delay, cb: cb())
        win._win.hide = lambda: calls.append("tray-hide")
        win._show_initial_window()
        assert calls == ["show", "tray-hide"]
    finally:
        win._tray.hide()
        win.hide_window()


def test_start_minimized_falls_back_to_taskbar_when_tray_icon_not_visible(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
        start_minimized=True,
    )

    try:
        calls = []
        win._tray._available = True
        monkeypatch.setattr(type(win._tray), "is_visible", property(lambda self: False))
        win._win.show = lambda: calls.append("show")
        win._win.hide = lambda: calls.append("hide")
        win._win.showMinimized = lambda: calls.append("minimized")
        monkeypatch.setattr("src.gui.main_window.QTimer.singleShot", lambda delay, cb: cb())
        win._show_initial_window()
        assert calls == ["show", "minimized"]
    finally:
        win._tray.hide()
        win.hide_window()


def test_minimize_event_does_not_hide_window_when_tray_icon_not_visible(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
    )

    class WindowStateEvent:
        def type(self):
            from PyQt5.QtCore import QEvent

            return QEvent.WindowStateChange

    try:
        from PyQt5.QtCore import Qt

        calls = []
        win._tray._available = True
        monkeypatch.setattr(type(win._tray), "is_visible", property(lambda self: False))
        monkeypatch.setattr(win._win, "windowState", lambda: Qt.WindowMinimized)
        win._win.hide = lambda: calls.append("hide")

        assert win.eventFilter(win._win, WindowStateEvent()) is False
        assert calls == []
    finally:
        win._tray.hide()
        win.hide_window()


def test_start_normal_uses_show(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    win = MainWindow(
        app_name="Test App",
        app_version="1.0",
        company="Test",
        agent_name="agent",
        icon_path="",
        log_path="test.log",
        on_restart=lambda: None,
        on_stop=lambda: None,
        on_start=lambda: None,
        on_exit=lambda: None,
        on_show_log=lambda: None,
        dark_theme=False,
        start_minimized=False,
    )

    try:
        calls = []
        win._win.showMinimized = lambda: calls.append("minimized")
        win._win.show = lambda: calls.append("show")
        win._show_initial_window()
        assert calls == ["show"]
    finally:
        win._tray.hide()
        win.hide_window()


def test_calculate_uptime_seconds_uses_windows_filetime_epoch():
    created_unix_seconds = 1_700_000_000
    now_unix_seconds = created_unix_seconds + 125
    created_100ns = int((created_unix_seconds + FILETIME_UNIX_EPOCH_OFFSET_SECONDS) * 10_000_000)

    assert MainWindow._calculate_uptime_seconds(created_100ns, now_unix_seconds=now_unix_seconds) == 125
