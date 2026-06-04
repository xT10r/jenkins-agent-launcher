"""
Защита от запуска нескольких экземпляров с одинаковыми настройками.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from .config import AppConfig


def _is_process_alive(pid: int) -> bool:
    """Проверить, существует ли процесс."""
    if pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _instance_signature(config: AppConfig) -> str:
    """Сигнатура конфигурации, по которой запрещаем дубликаты."""
    payload = {
        "jenkins_url": config.agent.jenkins_url.strip().lower(),
        "agent_name": config.agent.agent_name.strip().lower(),
        "workdir": config.agent.workdir.strip().lower(),
        "agent_jar_path": config.agent.agent_jar_path.strip().lower(),
        "temp_dir": config.agent.temp_dir.strip().lower(),
        "tunnel": config.agent.tunnel.strip().lower(),
        "direct": config.agent.direct.strip().lower(),
        "websocket": bool(config.agent.websocket),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


class ConfigInstanceGuard:
    """Файловый lock для одного набора настроек."""

    def __init__(self, config: AppConfig, root_dir: Path | None = None):
        self._signature = _instance_signature(config)
        self._root_dir = Path(root_dir or Path(tempfile.gettempdir()) / "jenkins-agent-launcher-locks")
        self._path = self._root_dir / f"{self._signature}.lock"
        self._acquired = False

    @property
    def path(self) -> Path:
        return self._path

    def acquire(self) -> tuple[bool, str | None]:
        """Попробовать захватить lock. Вернуть (ok, message)."""
        self._root_dir.mkdir(parents=True, exist_ok=True)

        if self._try_create_lock():
            self._acquired = True
            return True, None

        owner_pid = self._read_owner_pid()
        if owner_pid and _is_process_alive(owner_pid):
            return False, f"Уже запущен экземпляр с теми же настройками (PID {owner_pid})"

        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            return False, f"Не удалось обновить lock-файл экземпляра: {exc}"

        if self._try_create_lock():
            self._acquired = True
            return True, None

        owner_pid = self._read_owner_pid()
        if owner_pid and _is_process_alive(owner_pid):
            return False, f"Уже запущен экземпляр с теми же настройками (PID {owner_pid})"
        return False, "Не удалось захватить lock экземпляра"

    def release(self):
        """Освободить lock текущего процесса."""
        if not self._acquired:
            return

        owner_pid = self._read_owner_pid()
        if owner_pid and owner_pid != os.getpid():
            self._acquired = False
            return

        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        finally:
            self._acquired = False

    def _try_create_lock(self) -> bool:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(str(self._path), flags)
        except FileExistsError:
            return False

        try:
            payload = json.dumps({"pid": os.getpid()}, ensure_ascii=True)
            os.write(fd, payload.encode("utf-8"))
        finally:
            os.close(fd)
        return True

    def _read_owner_pid(self) -> int | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return None

        try:
            return int(payload.get("pid"))
        except Exception:
            return None
