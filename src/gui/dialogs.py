"""Диалоги: Справка, О программе."""

from __future__ import annotations

import datetime
import os
import sys


def show_help(parent, app_name: str, app_version: str):
    from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QTextEdit, QVBoxLayout

    text = (
        f"{app_name} v{app_version}\n\n"
        "Запуск Jenkins JNLP agent в пользовательской сессии.\n\n"
        "РЕЖИМЫ:\n"
        "  --test-config       Проверить конфигурацию\n"
        "  --no-gui            Консольный режим\n\n"
        "ПОДКЛЮЧЕНИЕ:\n"
        "  --url <URL>         Jenkins-сервер (обязательно)\n"
        "  --name <NAME>       Имя агента (обязательно)\n"
        "  --secret <SECRET>   Секрет из Jenkins UI (обязательно)\n"
        "  --tunnel <H:P>      Туннель для TCP-трафика\n"
        "  --direct <H:P>      Прямое TCP-подключение\n"
        "  --instanceIdentity  Публичный ключ контроллера\n"
        "  --protocols <LIST>  Ограничение протоколов (JNLP4-connect)\n"
        "  --java-opts <OPTS>  JVM-опции для Java-процесса\n"
        "  --java-home <PATH>  Путь к JDK/JRE или к java.exe\n"
        "  --temp-dir <PATH>   Временный каталог Java/launcher\n"
        "  --websocket         Использовать WebSocket\n\n"
        "ПУТИ:\n"
        "  --work-dir <PATH>   Рабочая директория агента\n"
        "  --jar-path <PATH>   Путь к agent.jar\n"
        "  --log-path <PATH>   Путь к лог-файлу\n"
        "  --fallback-url <URL> Резервный URL для agent.jar\n\n"
        "ПОВЕДЕНИЕ:\n"
        "  --max-restarts <N>  Макс. рестартов (-1=∞, 0=нет)\n"
        "  --restart-delay <S> Задержка между рестартами (сек)\n"
        "  --timeout <S>       Таймаут проверки Jenkins (сек)\n"
        "  --auto-update       Обновлять agent.jar автоматически\n"
        "  --no-auto-update    Не обновлять agent.jar\n\n"
        "ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:\n"
        "  JENKINS_SECRET              Секрет агента\n"
        "  JENKINS_AGENT_NAME          Имя агента\n"
        "  JENKINS_TUNNEL              Туннель (H:P)\n"
        "  JENKINS_WEB_SOCKET          WebSocket (true/false)\n"
        "  JENKINS_DIRECT_CONNECTION   Прямое подключение (H:P)\n"
        "  JENKINS_INSTANCE_IDENTITY   Публичный ключ контроллера\n"
        "  JENKINS_PROTOCOLS           Список протоколов\n"
        "  JENKINS_JAVA_OPTS           JVM-опции\n"
        "  JENKINS_TEMP_DIR            Временный каталог Java/launcher\n"
        "  JENKINS_FALLBACK_JAR_PATH   Резервный URL для agent.jar\n\n"
        "  JAVA_HOME                   Используется как fallback, если javaHome не задан и java нет в PATH\n\n"
        "ИСТОЧНИКИ: defaults → config.json → CLI → ENV\n"
        "ПОДРОБНЕЕ: docs/README.md"
    )
    dialog = QDialog(parent)
    dialog.setWindowTitle("Справка")
    dialog.resize(760, 600)
    dialog.setMinimumSize(640, 480)

    layout = QVBoxLayout(dialog)
    help_text = QTextEdit(dialog)
    help_text.setReadOnly(True)
    help_text.setPlainText(text)
    layout.addWidget(help_text)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec_()


def show_about(parent, app_name: str, app_version: str, company: str, icon_path: str = ""):
    from PyQt5.QtGui import QIcon
    from PyQt5.QtWidgets import QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout
    from PyQt5.QtCore import Qt

    year = datetime.datetime.now().year
    text = (
        f"<h2>{app_name}</h2>"
        f"<p>Версия: <b>{app_version}</b></p>"
        f"<p>Python {sys.version.split()[0]}</p>"
        f"<p>Запуск Jenkins JNLP agent в пользовательской сессии<br>"
        f"с tray-иконкой, live-логом и автоматическим рестартом.</p>"
        f"<p><b>Функции:</b></p>"
        f"<ul>"
        f"<li>Скрытие JENKINS_* переменных от дочернего процесса</li>"
        f"<li>Секрет через @file (не в CLI)</li>"
        f"<li>Изоляция чувствительных переменных окружения</li>"
        f"<li>Каскад скачивания: SSL → no-secure → fallback</li>"
        f"<li>Автоматический рестарт при падении (настраиваемый лимит)</li>"
        f"<li>Retry при скачивании (3 попытки, exponential backoff)</li>"
        f"<li>Прогресс загрузки agent.jar</li>"
        f"<li>Тёмная тема (Ctrl+T)</li>"
        f"<li>Три режима: GUI, Console, Test-Config</li>"
        f"</ul>"
        f"<p><b>Конфигурация:</b> defaults → config.json → CLI → ENV</p>"
        f"<p><b>Документация:</b> docs/README.md</p>"
        f"<p><b>Спецификация:</b> docs/specification.md</p>"
        f"<p>© {year} {company}</p>"
    )
    dialog = QDialog(parent)
    dialog.setWindowTitle("О программе")
    dialog.resize(960, 880)
    dialog.setMinimumSize(760, 640)

    layout = QVBoxLayout(dialog)
    content_layout = QHBoxLayout()
    content_layout.setSpacing(18)
    layout.addLayout(content_layout)

    if icon_path and os.path.isfile(icon_path):
        icon = QIcon(icon_path)
        dialog.setWindowIcon(icon)
        icon_label = QLabel(dialog)
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        icon_label.setFixedWidth(112)
        icon_label.setPixmap(icon.pixmap(96, 96))
        content_layout.addWidget(icon_label)

    about_text = QLabel(dialog)
    about_text.setTextFormat(Qt.RichText)
    about_text.setWordWrap(True)
    about_text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
    about_text.setText(text)
    about_text.setStyleSheet("background: transparent;")

    scroll = QScrollArea(dialog)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setStyleSheet("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget { background: transparent; }")
    scroll.setWidget(about_text)
    content_layout.addWidget(scroll, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.Ok, dialog)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec_()
