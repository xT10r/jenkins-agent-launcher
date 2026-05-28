"""Tray-иконка с контекстным меню и уведомлениями."""

from __future__ import annotations

import os

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QMenu, QSystemTrayIcon


class TrayIcon:
    def __init__(
        self,
        app_name: str,
        agent_name: str,
        icon_path: str,
        on_restart,
        on_stop,
        on_exit,
        on_show,
        on_show_log,
    ):
        self.icon_path = icon_path
        self.agent_name = agent_name
        self._app_name = app_name
        self._available = QSystemTrayIcon.isSystemTrayAvailable()

        icon = QIcon(icon_path) if os.path.isfile(icon_path) else None
        self._tray = QSystemTrayIcon(icon or QIcon())
        self._tray.setToolTip(f"{app_name}: {agent_name}")

        self._menu = QMenu()
        self._status_action = self._menu.addAction("Статус: Запуск...")
        self._status_action.setEnabled(False)
        self._menu.addSeparator()
        self._menu.addAction("Показать окно", on_show)
        self._menu.addAction("Показать лог", on_show_log)
        self._menu.addSeparator()
        self._menu.addAction("Перезапуск", on_restart)
        self._menu.addAction("Стоп", on_stop)
        self._menu.addSeparator()
        self._menu.addAction("Выход", on_exit)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(
            lambda r: on_show() if r in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None
        )
        if self._available:
            self.show()

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_visible(self) -> bool:
        return self._available and self._tray.isVisible()

    def show(self):
        if self._available:
            self._tray.show()

    def set_status(self, text: str):
        self._status_action.setText(f"Статус: {text}")

    def notify(self, title: str, message: str, duration: int = 3000):
        """Показать всплывающее уведомление в tray."""
        if self._available and self._tray.isVisible():
            self._tray.showMessage(
                title, message, QSystemTrayIcon.Information, duration
            )

    def notify_warning(self, title: str, message: str, duration: int = 5000):
        """Показать предупреждение в tray."""
        if self._available and self._tray.isVisible():
            self._tray.showMessage(
                title, message, QSystemTrayIcon.Warning, duration
            )

    def hide(self):
        self._tray.hide()
