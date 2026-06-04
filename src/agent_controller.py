"""
Оркестратор: скачивание → запуск → мониторинг → рестарт.
Не зависит от GUI - вызывает callback'и для обновления UI.
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import requests

from .config import AppConfig
from .downloader import AgentJarDownloader
from .jnlp import JnlpSecretResolver
from .logger import RotatingLogger
from .process import AgentProcess, resolve_java_command
from .ssl_check import check_ssl


class AgentController:
    """Управление жизненным циклом Jenkins-агента."""

    def __init__(
        self,
        config: AppConfig,
        logger: RotatingLogger,
        on_status: Callable[[str, int], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        updated_via_self_update: bool = False,
        post_update_session_path: str | None = None,
        update_manager: object | None = None,
    ):
        self.config = config
        self.log = logger
        self.on_status = on_status or (lambda *a: None)
        self.on_progress = on_progress or (lambda *a: None)
        self.updated_via_self_update = updated_via_self_update
        self.post_update_session_path = post_update_session_path
        self.update_manager = update_manager

        self._stop = threading.Event()
        self._process: AgentProcess | None = None
        self._restart_count = 0
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._agent_connection_state = ""

    # ── Public ──

    def start(self):
        """Запустить оркестратор в фоне."""
        with self._state_lock:
            if self._thread is not None and self._thread.is_alive():
                self._safe_log("Запуск пропущен: экземпляр контроллера уже работает", level="WARN", comp="Launcher")
                return

            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self):
        """Остановить оркестратор."""
        self._stop.set()
        if self._process:
            self._process.stop()
        if self._thread:
            self._thread.join(timeout=10)

    def restart(self):
        """Перезапуск по запросу пользователя."""
        self._restart_count = 0
        self._stop.set()
        current_thread = self._thread
        if self._process:
            if not self._process.owns_process:
                self._safe_log(
                    "Подхваченный java-процесс будет корректно остановлен и перезапущен по запросу пользователя.",
                    comp="Launcher",
                )
            self._process.stop()
        if current_thread and current_thread.is_alive():
            current_thread.join(timeout=10)
        time.sleep(0.5)
        self.start()

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Internal ──

    def _run(self):
        a = self.config.agent
        b = self.config.behavior
        java_cmd: str | None = None

        self._set_status("Запуск...")

        # 1. Check Jenkins
        try:
            requests.head(f"{a.jenkins_url}/api/json", timeout=b.jenkins_timeout)
            self._safe_log("Jenkins-сервер доступен", comp="Launcher")
        except Exception as e:
            self._safe_log(f"Jenkins-сервер недоступен: {e}", level="WARN", comp="Launcher")

        self._restart_count = 0

        while not self._stop.is_set():
            if self.config.jnlp.enabled:
                resolver = JnlpSecretResolver(self.config, log_fn=self._safe_log)
                if not resolver.ensure_secret():
                    self._set_status("Нет secret")
                    self._fail_post_update("Не удалось получить Jenkins secret из JNLP после self-update")
                    return

            proc = AgentProcess(
                jenkins_url=a.jenkins_url,
                agent_jar=a.agent_jar_path,
                agent_name=a.agent_name,
                workdir=a.workdir,
                secret=a.secret,
                tunnel=a.tunnel,
                websocket=a.websocket,
                direct=a.direct,
                instance_identity=a.instance_identity,
                protocols=a.protocols,
                java_opts=a.java_opts,
                java_home=a.java_home,
                temp_dir=a.temp_dir,
                java_cmd=java_cmd,
                isolated_vars=[item.name for item in self.config.environment.ignored_vars],
                on_line=self._handle_agent_output,
            )
            self._process = proc
            self._agent_connection_state = ""

            match = proc.find_matching_process()
            if match.status == "ambiguous":
                candidate_pids = ", ".join(str(item.pid) for item in match.candidates)
                self._safe_log(
                    f"Найдено несколько подходящих java-процессов Jenkins-агента ({candidate_pids}). "
                    "Launcher не будет угадывать, какой процесс подхватить.",
                    level="ERROR",
                    comp="Launcher",
                )
                self._set_status("Неоднозначный процесс")
                self._fail_post_update(
                    f"После self-update найдено несколько кандидатов для reattach: {candidate_pids}"
                )
                return

            if match.status == "matched" and match.process is not None:
                pid = proc.attach(match.process)
                if self.updated_via_self_update:
                    self._safe_log(
                        f"После self-update подхвачен существующий java-процесс Jenkins-агента (PID {pid}). "
                        "Новый launcher продолжает работу без запуска дубликата.",
                        comp="Launcher",
                    )
                else:
                    self._safe_log(
                        f"Подхвачен существующий java-процесс Jenkins-агента (PID {pid}). "
                        "Текущий launcher продолжит управлять им и сможет штатно остановить или перезапустить его.",
                        comp="Launcher",
                    )
                self._set_status("Работает (подхвачен)", pid)
                self._complete_post_update(attached_to_existing_agent=True, agent_pid=pid)
            else:
                # `attach` проверяем до локального download/java-check, чтобы self-update
                # мог подхватить уже живой java-agent даже при временно отсутствующем agent.jar.
                if b.auto_update or not __import__("os").path.isfile(a.agent_jar_path):
                    dc = self.config.download
                    dl = AgentJarDownloader(
                        jenkins_url=a.jenkins_url,
                        dest_path=a.agent_jar_path,
                        fallback_url=a.fallback_jar_url,
                        jenkins_verify_ssl=self.config.effective_agent_verify_ssl(),
                        fallback_verify_ssl=dc.fallback_verify_ssl,
                        timeout=dc.timeout,
                        chunk_size=dc.chunk_size,
                        log_fn=self._safe_log,
                        max_retries=dc.max_retries,
                        retry_delay=dc.retry_delay,
                        progress_fn=self.on_progress,
                    )
                    if not dl.ensure_jar():
                        self._set_status("Нет agent.jar")
                        self._safe_log("Не удалось загрузить agent.jar", level="ERROR")
                        self._fail_post_update("Не удалось подготовить agent.jar после self-update")
                        return

                if not __import__("os").path.isfile(a.agent_jar_path):
                    self._set_status("Нет agent.jar")
                    self._safe_log("agent.jar отсутствует", level="ERROR")
                    self._fail_post_update("После self-update отсутствует agent.jar для запуска нового процесса")
                    return

                if not java_cmd:
                    java_cmd, java_source = resolve_java_command(a.java_home)
                    if not java_cmd:
                        self._set_status("Java не найдена")
                        self._safe_log(java_source, level="ERROR")
                        self._fail_post_update("После self-update не найдена Java для запуска нового Jenkins-агента")
                        return
                    self._safe_log(f"Используется Java: {java_cmd} (источник: {java_source})", comp="Launcher")

                proc.java_cmd = java_cmd
                pid = proc.start()
                if pid is None:
                    self._set_status("Ошибка запуска")
                    self._fail_post_update("После self-update не удалось запустить новый java-процесс Jenkins-агента")
                    return

                if self.updated_via_self_update:
                    self._safe_log(
                        f"После self-update существующий java-процесс Jenkins-агента не найден; "
                        f"запущен новый процесс (PID {pid}).",
                        comp="Launcher",
                    )
                else:
                    self._safe_log(
                        f"Запущен новый java-процесс Jenkins-агента (PID {pid}) под управлением launcher.",
                        comp="Launcher",
                    )
                self._set_status("Работает", pid)
                self._complete_post_update(attached_to_existing_agent=False, agent_pid=pid)

            # Ждём завершения
            while not self._stop.is_set():
                time.sleep(2)
                if not proc.is_running:
                    break

            if self._stop.is_set():
                if proc.owns_process or not proc.is_running:
                    self._safe_log("Агент остановлен пользователем", comp="Launcher")
                else:
                    self._safe_log(
                        "Launcher остановлен пользователем; подхваченный java-процесс будет остановлен штатно.",
                        comp="Launcher",
                    )
                break

            code = proc.get_returncode()
            if proc.owns_process:
                self._safe_log(f"Java-процесс завершился с кодом {code}", level="WARN")
            else:
                self._safe_log(
                    f"Подхваченный java-процесс больше не найден (PID {proc.pid})",
                    level="WARN",
                    comp="Launcher",
                )
            proc.cleanup()

            if b.max_restarts == 0:
                self._safe_log("Автоматический перезапуск отключён (maxRestarts=0)", level="WARN")
                break
            if b.max_restarts > 0 and self._restart_count >= b.max_restarts:
                self._safe_log(f"Достигнут лимит перезапусков ({b.max_restarts})", level="ERROR")
                break

            self._restart_count += 1
            self._set_status(f"Перезапуск #{self._restart_count} через {b.restart_delay}с...")
            time.sleep(b.restart_delay)

        self._set_status("Остановлен")
        if self._process:
            self._process.stop()
            self._process.cleanup()
            self._process = None

    def _set_status(self, text: str, pid: int = 0):
        try:
            self.on_status(text, pid)
        except Exception:
            pass

    def _safe_log(self, msg: str, level: str = "INFO", comp: str = "Launcher") -> None:
        try:
            self.log.log(msg, level=level, comp=comp)
        except Exception:
            pass

    def _handle_agent_output(self, line: str) -> None:
        self._safe_log(line)
        status = self._agent_status_from_output(line)
        if status:
            self._set_agent_status(status)

    def _agent_status_from_output(self, line: str) -> str:
        text = line.lower()
        if "connection refused" in text:
            return "Не подключен: порт Jenkins недоступен"
        if "provided port:" in text and "not reachable" in text:
            return "Не подключен: порт Jenkins недоступен"
        if "could not locate server" in text:
            return "Не подключен: сервер агента недоступен"
        if "locating server among" in text:
            return "Подключение к Jenkins..."
        if "remoting server accepts" in text:
            return "Подключение: протокол найден"
        if "connected" in text and "connection refused" not in text:
            return "Подключен к Jenkins"
        return ""

    def _set_agent_status(self, text: str) -> None:
        is_error = text.startswith("Не подключен")
        if self._agent_connection_state.startswith("Не подключен") and not (
            is_error or text == "Подключен к Jenkins"
        ):
            return
        if text == self._agent_connection_state:
            return

        self._agent_connection_state = text
        pid = self._process.pid if self._process and self._process.pid else 0
        self._set_status(text, pid)

    def _complete_post_update(self, *, attached_to_existing_agent: bool, agent_pid: int) -> None:
        if not self.updated_via_self_update or self.update_manager is None:
            return
        try:
            self.update_manager.complete_post_restart(
                session_path=self.post_update_session_path,
                attached_to_existing_agent=attached_to_existing_agent,
                agent_pid=agent_pid,
            )
        except Exception as exc:
            self._safe_log(f"Не удалось завершить update-сессию после перезапуска: {exc}", level="ERROR", comp="Update")

    def _fail_post_update(self, reason: str) -> None:
        if not self.updated_via_self_update or self.update_manager is None:
            return
        try:
            self.update_manager.fail_post_restart(
                session_path=self.post_update_session_path,
                reason=reason,
            )
        except Exception as exc:
            self._safe_log(f"Не удалось пометить update-сессию как failed: {exc}", level="ERROR", comp="Update")
