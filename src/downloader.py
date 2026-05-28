"""
Скачивание agent.jar из Jenkins и fallback-источника.
Политика TLS задаётся явно через verify_ssl-флаги.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests


class AgentJarDownloader:
    """Загрузчик agent.jar."""

    def __init__(
        self,
        jenkins_url: str,
        dest_path: str,
        fallback_url: str = "",
        jenkins_verify_ssl: bool = True,
        fallback_verify_ssl: bool = True,
        timeout: int = 120,
        chunk_size: int = 8192,
        log_fn: Optional[Callable[..., None]] = None,
        max_retries: int = 3,
        retry_delay: int = 5,
        http_client: Any = None,
        progress_fn: Optional[Callable[[int, int], None]] = None,
    ):
        self.jenkins_url = jenkins_url
        self.dest_path = dest_path
        self.fallback_url = fallback_url
        self.jenkins_verify_ssl = jenkins_verify_ssl
        self.fallback_verify_ssl = fallback_verify_ssl
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.log = log_fn or (lambda *a, **kw: None)
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._http = http_client or requests
        self._progress_fn = progress_fn  # (downloaded, total) -> None

    def ensure_jar(self) -> bool:
        """
        Убедиться что agent.jar существует.
        Возвращает True если файл получен.
        """
        # Уже есть
        if os.path.isfile(self.dest_path):
            self.log("agent.jar найден - скачивание пропущено", comp="Download")
            return True

        # Создать директорию
        d = os.path.dirname(self.dest_path)
        if d and not os.path.isdir(d):
            try:
                os.makedirs(d, exist_ok=True)
            except Exception:
                pass

        url = f"{self.jenkins_url}/jnlpJars/agent.jar"

        # 1. Jenkins URL
        self.log(
            self._describe_download_start(
                source="Jenkins-сервера",
                url=url,
                verify_ssl=self.jenkins_verify_ssl,
            ),
            comp="Download",
        )
        if self._download_with_retry(url, verify=self.jenkins_verify_ssl):
            self.log("agent.jar успешно загружен", comp="Download")
            return True

        # 2. Fallback
        if self.fallback_url:
            self.log(
                self._describe_download_start(
                    source="резервного URL",
                    url=self.fallback_url,
                    verify_ssl=self.fallback_verify_ssl,
                ),
                comp="Fallback",
            )
            if self._download_with_retry(self.fallback_url, verify=self.fallback_verify_ssl):
                self.log("agent.jar загружен с резервного источника", comp="Fallback")
                return True
            self.log(f"Резервный URL недоступен: {self.fallback_url}", level="ERROR", comp="Fallback")

        self.log("Не удалось загрузить agent.jar ни из одного источника", level="ERROR", comp="Download")
        return False

    def _download_with_retry(self, url: str, verify: bool = True) -> bool:
        """Скачать файл с повторными попытками."""
        for attempt in range(self.max_retries):
            try:
                result = self._download(url, verify=verify)
                if result:
                    return True
            except Exception as e:
                if attempt < self.max_retries - 1:
                    self.log(f"Попытка {attempt+1}/{self.max_retries} не удалась: {e}", level="WARN", comp="Download")
                    time.sleep(self.retry_delay * (2 ** attempt))
                else:
                    self.log(f"Все {self.max_retries} попыток не удались: {e}", level="ERROR", comp="Download")
        return False

    def _download(self, url: str, verify: bool = True) -> bool:
        """Скачать файл по URL с поддержкой прогресса."""
        try:
            r = self._http.get(url, timeout=self.timeout, verify=verify, stream=True)
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            downloaded = 0

            with open(self.dest_path, "wb") as f:
                for chunk in r.iter_content(self.chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if self._progress_fn and total > 0:
                            self._progress_fn(downloaded, total)

            if self._progress_fn:
                self._progress_fn(total, total)  # 100%
            return True
        except Exception as e:
            self.log(f"Ошибка загрузки: {e}", level="ERROR", comp="Download")
            return False

    def _describe_download_start(self, source: str, url: str, verify_ssl: bool) -> str:
        scheme = urlparse(url).scheme.lower()
        if scheme != "https":
            return f"Загрузка agent.jar с {source} по незащищённому адресу ({scheme or 'unknown'})..."
        if verify_ssl:
            return f"Загрузка agent.jar с {source} c проверкой SSL..."
        return f"Загрузка agent.jar с {source} без проверки SSL (небезопасно)..."
