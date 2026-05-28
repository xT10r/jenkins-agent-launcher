"""
Переходные тесты: Jenkins доступен → недоступен → снова доступен.
Проверяем восстановление подключения и корректность логов.
"""

import os
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.config import AppConfig
from src.logger import RotatingLogger
from src.agent_controller import AgentController

TEST_VALUE = "test-value"


class FakeProcess:
    """Имитация java-процесса."""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.pid = 12345
        self._returncode = None
        self.stdout = iter([])
        self._timer = None
        if self.should_fail:
            self._timer = threading.Timer(0.5, self._kill)
            self._timer.start()

    def _kill(self):
        self._returncode = 1

    def poll(self):
        return self._returncode

    @property
    def is_running(self):
        return self._returncode is None

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
    return tmp_path


@pytest.fixture
def config(tmp_proj):
    jar = tmp_proj / "agent.jar"
    jar.write_bytes(b"fake jar")
    work = tmp_proj / "work"
    work.mkdir()

    cfg = AppConfig()
    cfg.agent.jenkins_url = "https://jenkins.example.com"
    cfg.agent.agent_name = "test-agent"
    cfg.agent.secret = (TEST_VALUE)
    cfg.agent.workdir = str(work)
    cfg.agent.agent_jar_path = str(jar)
    cfg.behavior.max_restarts = -1
    cfg.behavior.restart_delay = 1
    cfg.behavior.jenkins_timeout = 2
    return cfg


@pytest.fixture
def logger(tmp_proj):
    return RotatingLogger(tmp_proj)


def collect_log_lines(logger, timeout=0.5):
    """Дать буферу обработаться и вернуть записанные логи."""
    time.sleep(timeout)
    # Прочитать из файла
    log_files = list((tmp_proj / logger._log_dir_name).glob("*.log"))
    if not log_files:
        return []
    return log_files[0].read_text(encoding="utf-8").strip().split("\n")


# ── Тесты ──

class TestJenkinsOutage:
    """Jenkins доступен → недоступен → снова доступен."""

    def test_jenkins_comes_back_after_outage(self, config, logger, tmp_proj):
        """
        Сценарий:
        1. Jenkins доступен - агент запускается
        2. Jenkins недоступен 2 сек - агент падает
        3. Jenkins снова доступен - агент рестартит
        """
        jenkins_available = [True]
        statuses = []

        def mock_head(*args, **kwargs):
            if jenkins_available[0]:
                r = MagicMock()
                r.status_code = 200
                return r
            raise Exception("Jenkins недоступен")

        def mock_popen(*args, **kwargs):
            if not jenkins_available[0]:
                return FakeProcess(should_fail=True)
            return FakeProcess(should_fail=False)

        with patch("requests.head", side_effect=mock_head):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    ctrl = AgentController(config, logger, on_status=lambda t, p: statuses.append((t, p)))
                    ctrl.start()

                    # Фаза 1: Jenkins доступен (0-1 сек)
                    time.sleep(1)

                    # Фаза 2: Jenkins недоступен (1-3 сек) - процесс падает
                    jenkins_available[0] = False
                    time.sleep(3)

                    # Фаза 3: Jenkins снова доступен (3-5 сек) - рестарт
                    jenkins_available[0] = True
                    time.sleep(2)

                    ctrl.stop()

        # Проверяем логи
        log_dir = tmp_proj / "logs"
        if log_dir.exists():
            all_logs = []
            for f in log_dir.glob("*.log"):
                all_logs.extend(f.read_text(encoding="utf-8").split("\n"))
            full_text = "\n".join(all_logs)

            # Должно быть сообщение о доступности Jenkins
            assert "доступен" in full_text

            # Должна быть ошибка или остановка
            assert "недоступен" in full_text or "остановлен" in full_text

        # Статусы должны были меняться
        assert len(statuses) > 0

    def test_brief_outage_no_restart(self, config, logger, tmp_proj):
        """
        Кратковременная недоступность (менее restart_delay) - не должно рестартовать.
        """
        jenkins_available = [True]
        statuses = []

        def mock_head(*args, **kwargs):
            if jenkins_available[0]:
                r = MagicMock()
                r.status_code = 200
                return r
            raise Exception("Jenkins недоступен")

        def mock_popen(*args, **kwargs):
            return FakeProcess(should_fail=False)

        with patch("requests.head", side_effect=mock_head):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    cfg = config
                    cfg.behavior.restart_delay = 5  # Долгая задержка рестарта
                    cfg.behavior.max_restarts = 3

                    ctrl = AgentController(cfg, logger, on_status=lambda t, p: statuses.append((t, p)))
                    ctrl.start()

                    # Jenkins недоступен 2 сек
                    jenkins_available[0] = False
                    time.sleep(2)

                    # Jenkins снова доступен
                    jenkins_available[0] = True
                    time.sleep(1)

                    ctrl.stop()

        # Рестартов не должно быть (outage был кратковременным)
        restart_count = sum(1 for s in statuses if "Перезапуск" in s[0])
        assert restart_count == 0

    def test_permanent_outage_stops_after_max_restarts(self, config, logger, tmp_proj):
        """
        Jenkins стал недоступен навсегда - после maxRestars должен остановиться.
        """
        jenkins_available = [True]
        statuses = []

        def mock_head(*args, **kwargs):
            if jenkins_available[0]:
                r = MagicMock()
                r.status_code = 200
                return r
            raise Exception("Jenkins недоступен")

        def mock_popen(*args, **kwargs):
            return FakeProcess(should_fail=True)

        with patch("requests.head", side_effect=mock_head):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    cfg = config
                    cfg.behavior.max_restarts = 2
                    cfg.behavior.restart_delay = 1

                    ctrl = AgentController(cfg, logger, on_status=lambda t, p: statuses.append((t, p)))
                    ctrl.start()

                    # Jenkins сразу недоступен
                    jenkins_available[0] = False
                    time.sleep(6)

                    ctrl.stop()

        # Должно быть максимум 2 рестарта
        restart_count = sum(1 for s in statuses if "Перезапуск" in s[0])
        assert restart_count <= 2


class TestLogConsistency:
    """Проверка что логи пишутся корректно при переходах."""

    def test_log_has_startup_message(self, config, logger, tmp_proj):
        """При запуске должно быть сообщение о старте."""
        def mock_popen(*args, **kwargs):
            return FakeProcess(should_fail=False)

        def mock_head(*args, **kwargs):
            r = MagicMock()
            r.status_code = 200
            return r

        with patch("requests.head", side_effect=mock_head):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    ctrl = AgentController(config, logger)
                    ctrl.start()
                    time.sleep(0.5)
                    ctrl.stop()

        log_dir = tmp_proj / "logs"
        if log_dir.exists():
            content = ""
            for f in log_dir.glob("*.log"):
                content += f.read_text(encoding="utf-8")
            assert "доступен" in content

    def test_log_has_outage_message(self, config, logger, tmp_proj):
        """При недоступности Jenkins - должно быть предупреждение."""
        def mock_head(*args, **kwargs):
            raise Exception("Connection refused")

        def mock_popen(*args, **kwargs):
            return FakeProcess(should_fail=False)

        with patch("requests.head", side_effect=mock_head):
            with patch("subprocess.Popen", side_effect=mock_popen):
                with patch("shutil.which", return_value="/usr/bin/java"):
                    ctrl = AgentController(config, logger)
                    ctrl.start()
                    time.sleep(1)
                    ctrl.stop()

        log_dir = tmp_proj / "logs"
        if log_dir.exists():
            content = ""
            for f in log_dir.glob("*.log"):
                content += f.read_text(encoding="utf-8")
            # Должно быть сообщение о недоступности
            assert "недоступен" in content.lower() or "warn" in content.lower()
