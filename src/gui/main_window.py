"""Главное окно приложения."""

from __future__ import annotations

import ctypes
import os
import time
from ctypes import wintypes

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer
from PyQt5.QtGui import QFont, QIcon, QKeySequence, QPalette, QColor
from PyQt5.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QMainWindow,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
    QApplication, QStyleFactory, QAction, QGridLayout,
)

from .dialogs import show_help, show_about
from .tray_icon import TrayIcon


# Светлая тема
LIGHT_PALETTE = {
    QPalette.Window: QColor(240, 240, 240),
    QPalette.WindowText: QColor(0, 0, 0),
    QPalette.Base: QColor(255, 255, 255),
    QPalette.AlternateBase: QColor(245, 245, 245),
    QPalette.ToolTipBase: QColor(255, 255, 220),
    QPalette.ToolTipText: QColor(0, 0, 0),
    QPalette.Text: QColor(0, 0, 0),
    QPalette.Button: QColor(240, 240, 240),
    QPalette.ButtonText: QColor(0, 0, 0),
    QPalette.BrightText: QColor(255, 0, 0),
    QPalette.Link: QColor(42, 130, 218),
    QPalette.Highlight: QColor(42, 130, 218),
    QPalette.HighlightedText: QColor(255, 255, 255),
}

LIGHT_DISABLED = {
    QPalette.WindowText: QColor(120, 120, 120),
    QPalette.Text: QColor(120, 120, 120),
    QPalette.ButtonText: QColor(120, 120, 120),
}

# Тёмная тема
DARK_PALETTE = {
    QPalette.Window: QColor(53, 53, 53),
    QPalette.WindowText: QColor(255, 255, 255),
    QPalette.Base: QColor(25, 25, 25),
    QPalette.AlternateBase: QColor(53, 53, 53),
    QPalette.ToolTipBase: QColor(255, 255, 255),
    QPalette.ToolTipText: QColor(255, 255, 255),
    QPalette.Text: QColor(255, 255, 255),
    QPalette.Button: QColor(53, 53, 53),
    QPalette.ButtonText: QColor(255, 255, 255),
    QPalette.BrightText: QColor(255, 0, 0),
    QPalette.Link: QColor(42, 130, 218),
    QPalette.Highlight: QColor(42, 130, 218),
    QPalette.HighlightedText: QColor(0, 0, 0),
}

# Disabled цвета для тёмной темы (серый — виден на тёмном фоне)
DARK_DISABLED = {
    QPalette.WindowText: QColor(100, 100, 100),
    QPalette.Text: QColor(100, 100, 100),
    QPalette.ButtonText: QColor(100, 100, 100),
}


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
STILL_ACTIVE = 259
FILETIME_UNIX_EPOCH_OFFSET_SECONDS = 11644473600
STATUS_MARKERS = {
    "ok": "[OK]",
    "warn": "[WRN]",
    "err": "[ERR]",
}


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _OpenProcess = ctypes.WinDLL("kernel32", use_last_error=True).OpenProcess
    _OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OpenProcess.restype = wintypes.HANDLE
    _CloseHandle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    _CloseHandle.argtypes = [wintypes.HANDLE]
    _CloseHandle.restype = wintypes.BOOL
    _GetExitCodeProcess = _kernel32.GetExitCodeProcess
    _GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _GetExitCodeProcess.restype = wintypes.BOOL
    _GetProcessTimes = _kernel32.GetProcessTimes
    _GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    _GetProcessTimes.restype = wintypes.BOOL
    _GetProcessMemoryInfo = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    _GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
        wintypes.DWORD,
    ]
    _GetProcessMemoryInfo.restype = wintypes.BOOL
else:
    _OpenProcess = None
    _CloseHandle = None
    _GetExitCodeProcess = None
    _GetProcessTimes = None
    _GetProcessMemoryInfo = None


def _apply_palette(app: QApplication, colors: dict, disabled_colors: dict):
    """Применить единую палитру с общим стилем для обеих тем."""
    app.setStyle("Fusion")
    palette = QPalette()
    for role, color in colors.items():
        palette.setColor(role, color)
    for role, color in disabled_colors.items():
        palette.setColor(QPalette.Disabled, role, color)
    app.setPalette(palette)


def _apply_dark_palette(app: QApplication):
    """Применить тёмную тему к приложению."""
    _apply_palette(app, DARK_PALETTE, DARK_DISABLED)


def _apply_light_palette(app: QApplication):
    """Применить светлую тему к приложению."""
    _apply_palette(app, LIGHT_PALETTE, LIGHT_DISABLED)


class MainWindow(QObject):
    def __init__(
        self,
        app_name: str,
        app_version: str,
        company: str,
        agent_name: str,
        icon_path: str,
        log_path: str,
        on_restart,
        on_stop,
        on_start,
        on_exit,
        on_show_log,
        on_theme_change=None,
        dark_theme: bool = False,
        start_minimized: bool = True,
        launcher_pid: int = 0,
        parent_pid: int = 0,
    ):
        super().__init__()
        from PyQt5.QtWidgets import QApplication
        self._app = QApplication.instance() or QApplication([app_name])
        self._app.setQuitOnLastWindowClosed(False)

        self._on_theme_change = on_theme_change
        if dark_theme:
            _apply_dark_palette(self._app)
        else:
            _apply_light_palette(self._app)

        self._app_name = app_name
        self._app_version = app_version
        self._company = company
        self._icon_path = icon_path
        self._log_path = log_path
        self._dark_theme = dark_theme
        self._start_minimized = start_minimized
        self._proc_running = False
        self._launcher_pid = launcher_pid
        self._parent_pid = parent_pid
        self._java_pid = 0
        self._current_status_text = "Инициализация..."

        # ── Window ──
        self._win = QMainWindow()
        title = f"{app_name} - {agent_name}" if agent_name else app_name
        self._win.setWindowTitle(f"{title} v{app_version}")
        self._win.setMinimumSize(1200, 800)
        if __import__("os").path.isfile(icon_path):
            self._win.setWindowIcon(QIcon(icon_path))

        # Сохраняем callback'и (до _build_ui — кнопки подключаются к ним)
        self._on_exit = on_exit
        self._on_start = on_start
        self._on_restart = on_restart
        self._on_stop = on_stop
        self._on_show_log = on_show_log

        self._build_ui()
        self._build_menu()
        self._win.resize(1200, 800)

        # ── Tray ──
        self._tray = TrayIcon(
            app_name=app_name,
            agent_name=agent_name,
            icon_path=icon_path,
            on_restart=on_restart,
            on_stop=on_stop,
            on_exit=on_exit,
            on_show=self.show_window,
            on_show_log=on_show_log,
        )

        # Close → выход из приложения
        self._win.closeEvent = lambda e: self._do_exit()

        # Minimize → hide to tray (через eventFilter)
        self._win.installEventFilter(self)

        self._process_timer = QTimer(self)
        self._process_timer.setInterval(2000)
        self._process_timer.timeout.connect(self._refresh_process_status)
        self._process_timer.start()

    def eventFilter(self, obj, event):
        """Перехват событий окна: сворачивание → скрытие в трей."""
        if obj is self._win and event.type() == QEvent.WindowStateChange:
            if self._win.windowState() & Qt.WindowMinimized:
                return self.minimize_to_tray()
        return False  # Пропускаем остальные события дальше

    # ── Public ──

    def set_status(self, text: str, pid: int = 0):
        self._current_status_text = text
        self._java_pid = pid
        self._proc_running = self._is_running_status(text, pid)
        self._lbl_status.setText(text)
        self._refresh_process_status()
        self._tray.set_status(text)
        self._update_buttons()

    def append_log(self, line: str):
        """Добавить строку в live-лог (thread-safe через QTimer)."""
        display = line.replace("\t", "  ")
        QTimer.singleShot(0, lambda l=display: self._log_view.append(l))

    def notify(self, title: str, message: str):
        """Показать уведомление в tray."""
        self._tray.notify(title, message)

    def notify_warning(self, title: str, message: str):
        """Показать предупреждение в tray."""
        self._tray.notify_warning(title, message)

    def _toggle_theme(self):
        """Переключить тему."""
        self._dark_theme = not self._dark_theme
        if self._dark_theme:
            _apply_dark_palette(self._app)
        else:
            _apply_light_palette(self._app)

        self._update_theme_action_text()

        if self._on_theme_change:
            self._on_theme_change("dark" if self._dark_theme else "light")

    def show_window(self):
        self._win.showNormal()
        self._win.raise_()
        self._win.activateWindow()

    def hide_window(self):
        self._win.hide()

    def minimize_to_tray(self):
        """Спрятать окно в tray, если tray доступен и иконка показана."""
        if self._tray.is_available:
            self._tray.show()
            if self._tray.is_visible:
                self._win.hide()
                return True
        return False

    def _do_exit(self):
        """Реальный выход из приложения."""
        if self._on_exit:
            self._on_exit()

    def exec_(self) -> int:
        self._show_initial_window()
        return self._app.exec_()

    # ── UI Build ──

    def _build_ui(self):
        cw = QWidget()
        self._win.setCentralWidget(cw)
        lay = QVBoxLayout(cw)

        # Status
        sg = QGroupBox("Статус")
        sl = QVBoxLayout(sg)
        self._lbl_status = QLabel("Инициализация...")
        self._lbl_status.setFont(QFont("Consolas", 10))
        sl.addWidget(self._lbl_status)
        process_layout = QHBoxLayout()
        process_layout.addWidget(self._build_process_group("parent", "Parent"))
        process_layout.addWidget(self._build_process_group("launcher", "Launcher"))
        process_layout.addWidget(self._build_process_group("java", "Java"))
        sl.addLayout(process_layout)
        self._refresh_process_status()
        lay.addWidget(sg)

        # Buttons
        bl = QHBoxLayout()
        self._btn_start = QPushButton("▶ Запуск")
        self._btn_restart = QPushButton("⟳ Перезапуск")
        self._btn_stop = QPushButton("■ Остановить")
        bl.addWidget(self._btn_start)
        bl.addWidget(self._btn_restart)
        bl.addWidget(self._btn_stop)
        lay.addLayout(bl)

        # Подключаем кнопки
        self._btn_start.clicked.connect(self._on_start)
        self._btn_restart.clicked.connect(self._on_restart)
        self._btn_stop.clicked.connect(self._on_stop)

        # Log
        lg = QGroupBox("Лог")
        ll = QVBoxLayout(lg)
        self._log_view = QTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setFont(QFont("Consolas", 8))
        self._log_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._log_view.customContextMenuRequested.connect(self._show_log_context_menu)
        ll.addWidget(self._log_view)
        lay.addWidget(lg)

        self._update_buttons()

    def _build_menu(self):
        mb = self._win.menuBar()
        fm = mb.addMenu("Файл")
        self._act_start = fm.addAction("▶ Запустить")
        self._act_start.setShortcut(QKeySequence("F9"))
        self._act_start.triggered.connect(self._btn_start.click)

        self._act_restart = fm.addAction("⟳ Перезапустить")
        self._act_restart.setShortcut(QKeySequence("F5"))
        self._act_restart.triggered.connect(self._btn_restart.click)

        self._act_stop = fm.addAction("■ Остановить")
        self._act_stop.setShortcut(QKeySequence("Ctrl+S"))
        self._act_stop.triggered.connect(self._btn_stop.click)

        fm.addSeparator()
        fm.addAction("Открыть лог", self._open_log, QKeySequence("Ctrl+L"))
        fm.addSeparator()
        act_exit = fm.addAction("Выход")
        act_exit.setShortcut(QKeySequence("Ctrl+Q"))
        act_exit.triggered.connect(self._do_exit)  # Реальный выход

        # Вид → Тема
        vm = mb.addMenu("Вид")
        self._act_theme = vm.addAction("")
        self._act_theme.setShortcut(QKeySequence("Ctrl+T"))
        self._act_theme.triggered.connect(self._toggle_theme)
        self._update_theme_action_text()

        hm = mb.addMenu("Справка")
        hm.addAction("Справка", self._show_help, QKeySequence("F1"))
        hm.addAction("О программе", self._show_about)

    def _update_buttons(self):
        running = self._proc_running
        # Кнопки
        self._btn_start.setEnabled(not running)
        self._btn_restart.setEnabled(running)
        self._btn_stop.setEnabled(running)
        # Пункты меню — синхронно с кнопками
        if hasattr(self, '_act_start'):
            self._act_start.setEnabled(not running)
        if hasattr(self, '_act_restart'):
            self._act_restart.setEnabled(running)
        if hasattr(self, '_act_stop'):
            self._act_stop.setEnabled(running)

    def _show_log_context_menu(self, pos):
        """Контекстное меню лога: Copy, Select All, Clear."""
        menu = self._log_view.createStandardContextMenu()
        menu.addSeparator()
        act_clear = QAction("Clear", self._log_view)
        act_clear.triggered.connect(self._log_view.clear)
        menu.addAction(act_clear)
        menu.exec_(self._log_view.mapToGlobal(pos))

    def _open_log(self):
        import subprocess
        import os
        lp = self._log_path
        if os.path.isfile(lp):
            subprocess.Popen(["notepad.exe", lp])

    def _show_help(self):
        show_help(self._win, self._app_name, self._app_version)

    def _show_about(self):
        show_about(self._win, self._app_name, self._app_version, self._company, self._icon_path)

    def _update_theme_action_text(self):
        """Обновить подпись действия смены темы."""
        if hasattr(self, "_act_theme"):
            self._act_theme.setText("Переключить на светлую тему" if self._dark_theme else "Переключить на тёмную тему")

    @staticmethod
    def _is_running_status(text: str, pid: int) -> bool:
        normalized = text.strip().lower()
        if pid > 0:
            return True
        return normalized.startswith("работает")

    def _show_initial_window(self):
        if self._start_minimized:
            if self._tray.is_available:
                # Сначала показать окно, чтобы shell успел зарегистрировать tray-иконку,
                # затем скрыть его явно. Такой путь стабильнее на старых Windows.
                self._win.show()
                QTimer.singleShot(0, self._minimize_to_tray_or_taskbar)
            else:
                self._win.showMinimized()
        else:
            self._win.show()

    def _minimize_to_tray_or_taskbar(self):
        if not self.minimize_to_tray():
            self._win.showMinimized()

    def _refresh_process_status(self):
        process_info = {
            "parent": self._describe_process("Parent", self._parent_pid, treat_missing_as_error=False),
            "launcher": self._describe_process("Launcher", self._launcher_pid),
            "java": self._describe_process("Java", self._java_pid, status_text=self._current_status_text),
        }
        for key, info in process_info.items():
            fields = self._process_fields[key]
            fields["status"].setText(info["status"])
            fields["pid"].setText(info["pid"])
            fields["ram"].setText(info["memory"])
            fields["uptime"].setText(info["uptime"])

    def _build_process_group(self, key: str, title: str) -> QGroupBox:
        box = QGroupBox(title)
        grid = QGridLayout(box)
        labels: dict[str, QLabel] = {}
        for row, caption in enumerate(("Status", "PID", "RAM", "Uptime")):
            name = caption.lower()
            label = QLabel(f"{caption}:")
            value = QLabel("-")
            value.setFont(QFont("Consolas", 9))
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            labels[name] = value
        if not hasattr(self, "_process_fields"):
            self._process_fields: dict[str, dict[str, QLabel]] = {}
        self._process_fields[key] = labels
        return box

    def _describe_process(self, name: str, pid: int, treat_missing_as_error: bool = True, status_text: str = "") -> dict[str, str]:
        running = pid > 0 and self._is_pid_running(pid)
        normalized_status = status_text.strip().lower()

        if running and name == "Java":
            if "ошибка" in normalized_status:
                state = "warn"
            elif normalized_status.startswith("работает"):
                state = "ok"
            else:
                state = "ok"
        elif running:
            state = "ok"
        elif pid > 0:
            state = "warn"
        else:
            state = "err" if treat_missing_as_error else "warn"

        return {
            "status": STATUS_MARKERS[state],
            "pid": str(pid) if pid > 0 else "-",
            "memory": self._format_process_memory(pid) if running else "0 MB",
            "uptime": self._format_process_uptime(pid) if running else "-",
        }

    @staticmethod
    def _is_pid_running(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt" and _OpenProcess is not None and _GetExitCodeProcess is not None and _CloseHandle is not None:
            handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION, False, pid)
            if not handle:
                return False
            exit_code = wintypes.DWORD()
            try:
                if not _GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == STILL_ACTIVE
            finally:
                _CloseHandle(handle)
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _format_process_memory(self, pid: int) -> str:
        if pid <= 0:
            return "0 MB"

        if _OpenProcess is None or _GetProcessMemoryInfo is None or _CloseHandle is None:
            return "?"

        handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, pid)
        if not handle:
            return "?"

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        try:
            if not _GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                return "?"
        finally:
            _CloseHandle(handle)

        mb = max(0, int(round(counters.WorkingSetSize / (1024 * 1024))))
        return f"{mb} MB"

    def _format_process_uptime(self, pid: int) -> str:
        if pid <= 0:
            return "-"
        if os.name == "nt" and _OpenProcess is not None and _GetProcessTimes is not None and _CloseHandle is not None:
            handle = _OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_QUERY_INFORMATION, False, pid)
            if not handle:
                return "?"
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel = wintypes.FILETIME()
            user = wintypes.FILETIME()
            try:
                if not _GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
                    return "?"
            finally:
                _CloseHandle(handle)

            created_100ns = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
            if created_100ns <= 0:
                return "?"
            uptime_seconds = self._calculate_uptime_seconds(created_100ns)
            return self._format_duration(uptime_seconds)
        return "?"

    @staticmethod
    def _calculate_uptime_seconds(created_100ns: int, now_unix_seconds: float | None = None) -> int:
        if created_100ns <= 0:
            return 0
        if now_unix_seconds is None:
            now_unix_seconds = time.time()
        current_100ns = int((now_unix_seconds + FILETIME_UNIX_EPOCH_OFFSET_SECONDS) * 10_000_000)
        return max(0, (current_100ns - created_100ns) // 10_000_000)

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        hours, remainder = divmod(max(0, total_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
