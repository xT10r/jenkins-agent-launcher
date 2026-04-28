"""
Логирование с ротацией.
TSV-формат, буфер для GUI, автоочистка старых файлов.
"""

from __future__ import annotations

import datetime
import os
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

LOG_HEADER = "TIMESTAMP\tLEVEL\tCOMPONENT\tMESSAGE"


def _sanitize_message(msg: str) -> str:
    """Нормализовать строку лога: убрать control chars, emoji и лишние пробелы."""
    normalized = msg.replace("\t", " ").replace("\r\n", " | ").replace("\n", " | ")
    cleaned_chars: list[str] = []

    for ch in normalized:
        category = unicodedata.category(ch)
        if category.startswith("C"):
            continue
        if category in {"So", "Sk"}:
            continue
        cleaned_chars.append(ch)

    compact = "".join(cleaned_chars)
    compact = " ".join(compact.split())
    return compact.strip()


@dataclass(frozen=True)
class LogConfig:
    """Настройки логирования (immutable)."""
    dir: str = "logs"
    rotation: str = "daily"        # daily | weekly | never | size
    max_days: int = 14
    max_size_mb: int = 50
    path: str | None = None


class RotatingLogger:
    """Потокобезопасный логгер с ротацией."""

    def __init__(
        self,
        project_dir: Path,
        config: LogConfig | None = None,
    ):
        self._project_dir = project_dir
        self._config = config or LogConfig()
        self._lock = threading.Lock()
        self._file: object | None = None
        self._init = False
        self._on_line: Callable[[str], None] | None = None
        self._buffer: list[str] = []

    # ── Public API ──

    def set_gui_callback(self, cb: Callable[[str], None] | None):
        """Установить callback для GUI."""
        self._on_line = cb
        # Сбросить буфер
        if cb and self._buffer:
            for line in self._buffer:
                try:
                    cb(line)
                except Exception:
                    pass
            self._buffer.clear()

    def log(self, msg: str, level: str = "INFO", comp: str = "Launcher"):
        """Записать строку лога."""
        self._ensure_open()
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        safe = _sanitize_message(msg)
        entry = f"{ts}\t{level}\t{comp}\t{safe}"

        with self._lock:
            if self._file:
                try:
                    self._file.write(entry + "\n")
                    self._file.flush()
                except Exception:
                    pass
            if self._on_line:
                try:
                    self._on_line(entry)
                except Exception:
                    pass
            else:
                self._buffer.append(entry)

    def close(self):
        """Закрыть файл лога."""
        with self._lock:
            if self._file:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            self._init = False

    def get_current_path(self) -> str:
        """Путь к текущему файлу лога."""
        return self._log_path()

    # ── Internal ──

    def _log_path(self) -> str:
        now = datetime.datetime.now()
        if self._config.path:
            configured_path = Path(self._config.path)
            log_dir = configured_path.parent
            base = configured_path.stem
            suffix = configured_path.suffix or ".log"
        else:
            log_dir = self._project_dir / self._config.dir
            base = "jenkins-agent"
            suffix = ".log"

        if self._config.rotation == "daily":
            filename = f"{base}-{now.strftime('%Y-%m-%d')}{suffix}"
        elif self._config.rotation == "weekly":
            iso = now.isocalendar()
            filename = f"{base}-W{iso[1]:02d}-{iso[0]}{suffix}"
        else:
            filename = f"{base}{suffix}"

        return str(log_dir / filename)

    def _ensure_open(self):
        if self._init:
            # Rotation по размеру
            if self._config.rotation == "size":
                self._rotate_by_size()
                return

        lp = self._log_path()
        d = os.path.dirname(lp)
        if d and not os.path.isdir(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

        try:
            fresh = not os.path.isfile(lp) or os.path.getsize(lp) == 0
            self._file = open(lp, "a", encoding="utf-8")
            if fresh:
                self._file.write(LOG_HEADER + "\n")
                self._file.flush()
        except Exception:
            pass

        self._init = True

    def _rotate_by_size(self):
        if self._config.max_size_mb <= 0:
            return

        lp = self._log_path()
        if not os.path.isfile(lp):
            return

        size_mb = os.path.getsize(lp) / (1024 * 1024)
        if size_mb < self._config.max_size_mb:
            return

        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        rotated = lp.replace(".log", f"-{ts}.log")
        try:
            if self._file:
                self._file.flush()
                self._file.close()
                self._file = None
            os.rename(lp, rotated)
        except Exception:
            pass

    def cleanup_old(self):
        """Удалить файлы старше max_days."""
        if self._config.max_days <= 0:
            return

        log_dir = self._project_dir / self._config.dir
        if not log_dir.exists():
            return

        cutoff = datetime.datetime.now() - datetime.timedelta(days=self._config.max_days)
        cutoff_ts = cutoff.timestamp()

        for f in log_dir.iterdir():
            if f.is_file() and f.name.startswith("jenkins-agent") and f.suffix == ".log":
                try:
                    if f.stat().st_mtime < cutoff_ts:
                        f.unlink()
                except Exception:
                    pass
