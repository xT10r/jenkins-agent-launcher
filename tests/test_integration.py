"""
Интеграционные тесты: полный цикл config → download → process → restart.
"""

import os
import time
import threading
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.config import AppConfig, resolve_config
from src.logger import RotatingLogger, LogConfig
from src.agent_controller import AgentController
from src.downloader import AgentJarDownloader
from src.process import ProcessSnapshot
from src.self_update import SelfUpdateManager

TEST_VALUE = "test-value"


def _fake_pe_bytes(payload: bytes = b"binary") -> bytes:
    content = bytearray(256)
    content[0:2] = b"MZ"
    content[60:64] = (128).to_bytes(4, "little")
    content[128:132] = b"PE\x00\x00"
    content[132:132 + len(payload)] = payload
    return bytes(content)


def _write_fake_exe(path: Path, payload: bytes = b"binary") -> str:
    data = _fake_pe_bytes(payload)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


class FakeProcess:
    """Имитация java-процесса для интеграционных тестов."""

    def __init__(self, fail_after=0):
        self.pid = 99999
        self._returncode = None
        self.stdout = iter([])
        self._fail_after = fail_after
        self._timer = None
        if fail_after > 0:
            self._timer = threading.Timer(fail_after, self._kill)
            self._timer.start()

    def _kill(self):
        self._returncode = 1

    @property
    def is_running(self):
        return self._returncode is None

    def poll(self):
        return self._returncode

    def terminate(self):
        if self._timer:
            self._timer.cancel()
        self._returncode = 1

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        start = time.time()
        while self._returncode is None:
            if timeout and (time.time() - start) > timeout:
                return None
            time.sleep(0.05)
        return self._returncode


@pytest.fixture
def tmp_proj(tmp_path):
    """Создать временный проект с agent.jar."""
    jar = tmp_path / "agent.jar"
    jar.write_bytes(b"fake jar")
    work = tmp_path / "work"
    work.mkdir()
    return tmp_path


@pytest.fixture
def config(tmp_proj):
    """Валидная конфигурация для тестов."""
    cfg = AppConfig()
    cfg.agent.jenkins_url = "https://example.com"
    cfg.agent.agent_name = "test-agent"
    cfg.agent.secret = (TEST_VALUE)
    cfg.agent.workdir = str(tmp_proj / "work")
    cfg.agent.agent_jar_path = str(tmp_proj / "agent.jar")
    cfg.behavior.max_restarts = -1
    cfg.behavior.restart_delay = 1
    cfg.behavior.jenkins_timeout = 2
    return cfg


@pytest.fixture
def logger(tmp_proj):
    return RotatingLogger(tmp_proj, config=LogConfig(max_days=7))


class TestFullLifecycle:
    """Полный цикл работы агента."""

    def test_start_run_stop(self, config, logger, tmp_proj):
        """Запуск → работа → остановка."""
        statuses = []

        def mock_popen(*args, **kwargs):
            return FakeProcess(fail_after=0)  # Не падает

        with patch("requests.head") as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    ctrl = AgentController(
                        config, logger,
                        on_status=lambda t, p: statuses.append((t, p)),
                    )
                    ctrl.start()
                    time.sleep(0.5)
                    ctrl.stop()

        assert len(statuses) > 0
        # Должен быть статус "Работает"
        assert any("Работает" in s[0] for s in statuses)
        # Должен быть статус "Остановлен"
        assert any("Остановлен" in s[0] for s in statuses)

    def test_process_crash_and_restart(self, config, logger, tmp_proj):
        """Процесс падает → автоматический рестарт."""
        statuses = []
        crash_count = [0]

        def mock_popen(*args, **kwargs):
            crash_count[0] += 1
            if crash_count[0] <= 2:
                return FakeProcess(fail_after=0.3)  # Падает через 0.3с
            return FakeProcess(fail_after=0)  # Потом работает

        with patch("requests.head") as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    cfg = config
                    cfg.behavior.max_restarts = 5
                    cfg.behavior.restart_delay = 0.5  # Ускорить

                    ctrl = AgentController(
                        cfg, logger,
                        on_status=lambda t, p: statuses.append((t, p)),
                    )
                    ctrl.start()
                    time.sleep(3)
                    ctrl.stop()

        # Должны быть рестарты
        restart_count = sum(1 for s in statuses if "Перезапуск" in s[0])
        assert restart_count >= 1

    def test_download_on_startup(self, config, logger, tmp_proj):
        """Скачивание agent.jar при старте (если файла нет)."""
        jar_path = tmp_proj / "downloaded.jar"
        statuses = []

        config.agent.agent_jar_path = str(jar_path)

        def mock_popen(*args, **kwargs):
            return FakeProcess(fail_after=0)

        with patch("requests.head") as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    ctrl = AgentController(
                        config, logger,
                        on_status=lambda t, p: statuses.append((t, p)),
                    )
                    ctrl.start()
                    time.sleep(0.5)
                    ctrl.stop()

        assert len(statuses) > 0

    def test_max_restarts_exhausted(self, config, logger, tmp_proj):
        """Превышение лимита рестартов → остановка."""
        statuses = []

        def mock_popen(*args, **kwargs):
            return FakeProcess(fail_after=0.15)

        with patch("requests.head") as mock_head:
            mock_head.return_value = MagicMock(status_code=200)
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    cfg = config
                    cfg.behavior.max_restarts = 2
                    cfg.behavior.restart_delay = 0.2

                    ctrl = AgentController(
                        cfg, logger,
                        on_status=lambda t, p: statuses.append((t, p)),
                    )
                    ctrl.start()
                    time.sleep(6)
                    ctrl.stop()

        # Должно быть максимум 2 рестарта (может быть 1 или 2 в зависимости от тайминга)
        restart_count = sum(1 for s in statuses if "Перезапуск" in s[0])
        assert restart_count <= 2

    def test_self_update_restart_attaches_existing_agent_and_completes_session(self, config, logger, tmp_proj, monkeypatch):
        """После self-update launcher сначала подхватывает живой java-agent и только потом закрывает update-сессию."""
        statuses = []
        update_manager = SelfUpdateManager(logger=logger)
        source_exe = tmp_proj / "launcher-new.exe"
        target_exe = tmp_proj / "launcher.exe"
        sha256 = _write_fake_exe(source_exe, b"updated-launcher")
        _write_fake_exe(target_exe, b"current-launcher")

        session = update_manager.stage_update(
            config=config.update.__class__(
                enabled=True,
                local_path=str(source_exe),
                version="1.1.0.0",
                sha256=sha256,
            ),
            target_executable=target_exe,
            restart_args=["--no-gui"],
            current_version="1.0.0.0",
        )
        update_manager.transition_session(session, "applying_update")
        update_manager.transition_session(session, "restarting_launcher")
        finalized = update_manager.finalize_restart(session_path=session.session_file)
        assert finalized is not None
        assert finalized.state == "reattaching_agent"

        Path(config.agent.agent_jar_path).unlink(missing_ok=True)
        candidate = ProcessSnapshot(
            pid=4567,
            name="java.exe",
            command_line="java "
            "-Djenkins.launcher.role=agent-child "
            f"-jar {config.agent.agent_jar_path} "
            f"-url {config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {config.agent.agent_name} "
            f"-workDir {config.agent.workdir}",
        )

        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.process.list_java_processes", lambda: [candidate])
        monkeypatch.setattr("src.process._pid_is_running", lambda pid: pid == 4567)
        monkeypatch.setattr(
            "src.process.subprocess.Popen",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn not expected")),
        )

        ctrl = AgentController(
            config,
            logger,
            on_status=lambda t, p: statuses.append((t, p)),
            updated_via_self_update=True,
            post_update_session_path=session.session_file,
            update_manager=update_manager,
        )
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()

        assert any(text == "Работает (подхвачен)" and pid == 4567 for text, pid in statuses)
        assert not Path(session.session_file).exists()
        assert not Path(session.staged_executable).exists()
        assert not Path(session.backup_executable).exists()

    def test_self_update_restart_fails_safely_on_ambiguous_reattach_without_spawning_duplicate(self, config, logger, tmp_proj, monkeypatch):
        """Если после self-update найдено несколько кандидатов, launcher помечает update как failed и не плодит новый java-процесс."""
        statuses = []
        update_manager = SelfUpdateManager(logger=logger)
        source_exe = tmp_proj / "launcher-new.exe"
        target_exe = tmp_proj / "launcher.exe"
        sha256 = _write_fake_exe(source_exe, b"updated-launcher")
        _write_fake_exe(target_exe, b"current-launcher")

        session = update_manager.stage_update(
            config=config.update.__class__(
                enabled=True,
                local_path=str(source_exe),
                version="1.1.0.0",
                sha256=sha256,
            ),
            target_executable=target_exe,
            restart_args=["--no-gui"],
            current_version="1.0.0.0",
        )
        update_manager.transition_session(session, "applying_update")
        update_manager.transition_session(session, "restarting_launcher")
        finalized = update_manager.finalize_restart(session_path=session.session_file)
        assert finalized is not None
        assert finalized.state == "reattaching_agent"

        candidate_cmd = (
            "java "
            "-Djenkins.launcher.role=agent-child "
            f"-jar {config.agent.agent_jar_path} "
            f"-url {config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {config.agent.agent_name} "
            f"-workDir {config.agent.workdir}"
        )
        candidates = [
            ProcessSnapshot(pid=4567, name="java.exe", command_line=candidate_cmd),
            ProcessSnapshot(pid=4568, name="java.exe", command_line=candidate_cmd),
        ]

        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.process.list_java_processes", lambda: candidates)
        monkeypatch.setattr(
            "src.process.subprocess.Popen",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn not expected")),
        )

        ctrl = AgentController(
            config,
            logger,
            on_status=lambda t, p: statuses.append((t, p)),
            updated_via_self_update=True,
            post_update_session_path=session.session_file,
            update_manager=update_manager,
        )
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()

        failed_session = update_manager.load_session(session.session_file)
        assert failed_session is not None
        assert failed_session.state == "update_failed"
        assert "несколько кандидатов" in failed_session.error
        assert any(text == "Неоднозначный процесс" for text, _ in statuses)


class TestDownloaderIntegration:
    """Интеграционные тесты скачивания."""

    def test_download_with_progress(self, tmp_proj):
        """Проверка callback прогресса при скачивании."""
        progress_calls = []

        def mock_progress(dl, total):
            progress_calls.append((dl, total))

        import requests
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"content-length": "100"}
        mock_resp.iter_content = MagicMock(return_value=iter([b"x" * 50, b"y" * 50]))

        mock_http = MagicMock()
        mock_http.get.return_value = mock_resp

        jar_path = tmp_proj / "progress_test.jar"
        if jar_path.exists():
            jar_path.unlink()

        dl = AgentJarDownloader(
            jenkins_url="https://example.com",
            dest_path=str(jar_path),
            progress_fn=mock_progress,
            http_client=mock_http,
        )
        assert dl.ensure_jar() is True

        # Должны быть вызовы прогресса
        assert len(progress_calls) >= 2
        # Последний вызов - 100%
        assert progress_calls[-1] == (100, 100)

    def test_download_with_retry(self, tmp_proj):
        """Проверка retry при скачивании."""
        call_count = [0]

        import requests
        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise requests.exceptions.ConnectionError("refused")
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.iter_content.return_value = [b"jar content"]
            mock_resp.headers = {"content-length": "11"}
            return mock_resp

        mock_http = MagicMock()
        mock_http.get = mock_get

        jar_path = tmp_proj / "retry_test.jar"
        if jar_path.exists():
            jar_path.unlink()

        dl = AgentJarDownloader(
            jenkins_url="https://example.com",
            dest_path=str(jar_path),
            max_retries=3,
            retry_delay=0.01,
            http_client=mock_http,
        )
        assert dl.ensure_jar() is True

        assert call_count[0] == 3
