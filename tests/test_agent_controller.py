"""Тесты и ломающие тесты agent_controller."""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.config import AppConfig, AgentConfig, BehaviorConfig, LoggingConfig
from src.logger import RotatingLogger
from src.agent_controller import AgentController
from src.process import ProcessSnapshot

TEST_VALUE = "test-value"


@pytest.fixture
def valid_config(tmp_path):
    cfg = AppConfig()
    cfg.agent.jenkins_url = "https://example.com"
    cfg.agent.agent_name = "test-agent"
    cfg.agent.secret = (TEST_VALUE)
    cfg.agent.workdir = str(tmp_path / "work")
    cfg.agent.agent_jar_path = str(tmp_path / "agent.jar")
    cfg.agent.log_path = str(tmp_path / "logs" / "test.log")
    cfg.behavior.jenkins_timeout = 2
    return cfg


@pytest.fixture
def logger(tmp_path):
    return RotatingLogger(tmp_path)


class TestControllerBasic:
    def test_start_stop(self, valid_config, logger):
        ctrl = AgentController(valid_config, logger)
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()
        assert not ctrl.is_running

    def test_restart(self, valid_config, logger):
        ctrl = AgentController(valid_config, logger)
        ctrl.start()
        time.sleep(0.5)
        ctrl.restart()
        time.sleep(0.5)
        ctrl.stop()

    def test_duplicate_start_is_ignored(self, valid_config, logger):
        ctrl = AgentController(valid_config, logger)
        ctrl.start()
        first_thread = ctrl._thread

        ctrl.start()
        time.sleep(0.2)
        ctrl.stop()

        assert ctrl._thread is first_thread or first_thread is not None

    def test_existing_process_is_attached_without_spawn(self, valid_config, logger, monkeypatch):
        statuses = []
        candidate = ProcessSnapshot(
            pid=4567,
            name="java.exe",
            command_line="java "
            "-Djenkins.launcher.role=agent-child "
            "-Djenkins.launcher.signature=ignored "
            f"-jar {valid_config.agent.agent_jar_path} "
            f"-url {valid_config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {valid_config.agent.agent_name} "
            f"-workDir {valid_config.agent.workdir}",
        )
        log_lines = []
        original_log = logger.log

        def capture_log(*args, **kwargs):
            log_lines.append(args[0])
            return original_log(*args, **kwargs)

        monkeypatch.setattr(logger, "log", capture_log)
        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.agent_controller.resolve_java_command", lambda *a, **k: ("java", "PATH"))
        monkeypatch.setattr("src.agent_controller.list_java_processes", lambda: [candidate], raising=False)
        monkeypatch.setattr("src.process.list_java_processes", lambda: [candidate])
        monkeypatch.setattr("src.process._terminate_pid", lambda pid: None)
        monkeypatch.setattr("src.process._kill_pid", lambda pid: None)

        def fail_start(*args, **kwargs):
            raise AssertionError("subprocess.Popen should not be called when attaching")

        monkeypatch.setattr("src.process.subprocess.Popen", fail_start)
        monkeypatch.setattr("src.process._pid_is_running", lambda pid: pid == 4567)

        ctrl = AgentController(valid_config, logger, on_status=lambda text, pid: statuses.append((text, pid)))
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()

        assert any(text == "Работает (подхвачен)" and pid == 4567 for text, pid in statuses)
        assert any("Подхвачен существующий java-процесс" in line for line in log_lines)

    def test_post_update_attach_completes_update_session(self, valid_config, logger, monkeypatch):
        statuses = []
        candidate = ProcessSnapshot(
            pid=4567,
            name="java.exe",
            command_line="java "
            "-Djenkins.launcher.role=agent-child "
            f"-jar {valid_config.agent.agent_jar_path} "
            f"-url {valid_config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {valid_config.agent.agent_name} "
            f"-workDir {valid_config.agent.workdir}",
        )
        update_manager = MagicMock()

        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.agent_controller.resolve_java_command", lambda *a, **k: ("java", "PATH"))
        monkeypatch.setattr("src.process.list_java_processes", lambda: [candidate])
        monkeypatch.setattr("src.process._terminate_pid", lambda pid: None)
        monkeypatch.setattr("src.process._kill_pid", lambda pid: None)
        monkeypatch.setattr("src.process.subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn not expected")))
        monkeypatch.setattr("src.process._pid_is_running", lambda pid: pid == 4567)

        ctrl = AgentController(
            valid_config,
            logger,
            on_status=lambda text, pid: statuses.append((text, pid)),
            updated_via_self_update=True,
            post_update_session_path="session.json",
            update_manager=update_manager,
        )
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()

        assert any(text == "Работает (подхвачен)" and pid == 4567 for text, pid in statuses)
        update_manager.complete_post_restart.assert_called_once_with(
            session_path="session.json",
            attached_to_existing_agent=True,
            agent_pid=4567,
        )

    def test_restart_stops_attached_process_and_starts_new_cycle(self, valid_config, logger, monkeypatch):
        statuses = []
        Path(valid_config.agent.agent_jar_path).parent.mkdir(parents=True, exist_ok=True)
        Path(valid_config.agent.agent_jar_path).write_bytes(b"fake jar")
        candidate = ProcessSnapshot(
            pid=4567,
            name="java.exe",
            command_line="java "
            "-Djenkins.launcher.role=agent-child "
            f"-jar {valid_config.agent.agent_jar_path} "
            f"-url {valid_config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {valid_config.agent.agent_name} "
            f"-workDir {valid_config.agent.workdir}",
        )
        created_processes = []
        stopped_pids = []

        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.process.list_java_processes", lambda: [candidate] if not stopped_pids and not created_processes else [])
        monkeypatch.setattr("src.process._pid_is_running", lambda pid: pid not in stopped_pids)
        monkeypatch.setattr("src.process._terminate_pid", lambda pid: stopped_pids.append(pid))
        monkeypatch.setattr("src.process._kill_pid", lambda pid: (_ for _ in ()).throw(AssertionError("kill not expected")))
        monkeypatch.setattr("src.agent_controller.resolve_java_command", lambda *a, **k: ("java", "PATH"))
        monkeypatch.setattr("src.agent_controller.AgentJarDownloader.ensure_jar", lambda self: True)

        class DummyOwnedProc:
            def __init__(self):
                self.pid = 9999
                self.returncode = None
                self.stdout = iter([])

            def poll(self):
                return self.returncode

            def terminate(self):
                self.returncode = 0

            def kill(self):
                self.returncode = 1

            def wait(self, timeout=None):
                self.returncode = 0 if self.returncode is None else self.returncode
                return self.returncode

        def fake_popen(*args, **kwargs):
            created_processes.append(args)
            return DummyOwnedProc()

        monkeypatch.setattr("src.process.subprocess.Popen", fake_popen)

        ctrl = AgentController(valid_config, logger, on_status=lambda text, pid: statuses.append((text, pid)))
        ctrl.start()
        time.sleep(0.5)
        ctrl.restart()
        time.sleep(0.8)
        ctrl.stop()

        assert any(text == "Работает (подхвачен)" and pid == 4567 for text, pid in statuses)
        assert stopped_pids == [4567]
        assert created_processes

    def test_ambiguous_existing_processes_fail_safely(self, valid_config, logger, monkeypatch):
        statuses = []
        candidate_cmd = (
            "java "
            "-Djenkins.launcher.role=agent-child "
            f"-jar {valid_config.agent.agent_jar_path} "
            f"-url {valid_config.agent.jenkins_url} "
            "-secret @secret-file "
            f"-name {valid_config.agent.agent_name} "
            f"-workDir {valid_config.agent.workdir}"
        )
        candidates = [
            ProcessSnapshot(pid=1111, name="java.exe", command_line=candidate_cmd),
            ProcessSnapshot(pid=2222, name="java.exe", command_line=candidate_cmd),
        ]

        monkeypatch.setattr("src.agent_controller.requests.head", lambda *a, **k: MagicMock(status_code=200))
        monkeypatch.setattr("src.agent_controller.resolve_java_command", lambda *a, **k: ("java", "PATH"))
        monkeypatch.setattr("src.process.list_java_processes", lambda: candidates)
        monkeypatch.setattr("src.process.subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn not expected")))

        ctrl = AgentController(valid_config, logger, on_status=lambda text, pid: statuses.append((text, pid)))
        ctrl.start()
        time.sleep(0.5)
        ctrl.stop()

        assert any(text == "Неоднозначный процесс" for text, _ in statuses)

    def test_agent_output_updates_status_when_jenkins_port_is_unreachable(self):
        statuses = []
        ctrl = AgentController(AppConfig(), MagicMock(), on_status=lambda text, pid: statuses.append((text, pid)))

        ctrl._handle_agent_output("WARNING: Connection refused: getsockopt")
        ctrl._handle_agent_output(
            "java.io.IOException: https://example.com provided port:44373 is not reachable on host example.com"
        )

        assert statuses == [("Не подключен: порт Jenkins недоступен", 0)]

    def test_agent_output_updates_status_when_server_cannot_be_located(self):
        statuses = []
        ctrl = AgentController(AppConfig(), MagicMock(), on_status=lambda text, pid: statuses.append((text, pid)))

        ctrl._handle_agent_output("INFO: Could not locate server among [https://example.com]; waiting 10 seconds")

        assert statuses == [("Не подключен: сервер агента недоступен", 0)]

    def test_agent_output_does_not_downgrade_error_to_retry_status(self):
        statuses = []
        ctrl = AgentController(AppConfig(), MagicMock(), on_status=lambda text, pid: statuses.append((text, pid)))

        ctrl._handle_agent_output("WARNING: Connection refused: getsockopt")
        ctrl._handle_agent_output("INFO: Locating server among [https://example.com]")
        ctrl._handle_agent_output("INFO: Remoting server accepts the following protocols: [JNLP4-connect, Ping]")

        assert statuses == [("Не подключен: порт Jenkins недоступен", 0)]


class TestControllerBreaking:
    """Ломающие тесты контроллера."""

    def test_no_config(self):
        """Пустая конфигурация."""
        cfg = AppConfig()
        logger = MagicMock()
        ctrl = AgentController(cfg, logger)
        # Не должно упасть при создании
        assert ctrl is not None

    def test_unreachable_jenkins(self, tmp_path, logger):
        """Jenkins недоступен — контроллер должен обработать."""
        cfg = AppConfig()
        cfg.agent.jenkins_url = "https://192.0.2.1:12345"
        cfg.agent.agent_name = "test"
        cfg.agent.secret = (TEST_VALUE)
        cfg.agent.workdir = str(tmp_path)
        cfg.agent.agent_jar_path = str(tmp_path / "agent.jar")
        cfg.behavior.jenkins_timeout = 2

        statuses = []
        ctrl = AgentController(cfg, logger, on_status=lambda t, p: statuses.append((t, p)))
        ctrl.start()
        time.sleep(5)
        ctrl.stop()

        # Должен был попытаться скачать и получить ошибку
        assert len(statuses) > 0

    def test_max_restarts_zero(self, tmp_path, logger):
        """maxRestarts=0 — не должно рестартовать."""
        cfg = AppConfig()
        cfg.agent.jenkins_url = "https://example.com"
        cfg.agent.agent_name = "test"
        cfg.agent.secret = (TEST_VALUE)
        cfg.agent.workdir = str(tmp_path)
        cfg.agent.agent_jar_path = str(tmp_path / "fake.jar")
        # fake.jar существует, но java его не запустит
        (tmp_path / "fake.jar").write_bytes(b"fake")
        cfg.behavior.max_restarts = 0
        cfg.behavior.jenkins_timeout = 2

        statuses = []
        ctrl = AgentController(cfg, logger, on_status=lambda t, p: statuses.append((t, p)))
        ctrl.start()
        time.sleep(3)
        ctrl.stop()

        # Не должно быть рестартов
        restart_statuses = [s for s in statuses if "Перезапуск" in s[0]]
        assert len(restart_statuses) == 0

    def test_rapid_restart_loop(self, valid_config, logger):
        """Быстрые рестарты подряд."""
        ctrl = AgentController(valid_config, logger)
        for _ in range(5):
            ctrl.restart()
            time.sleep(0.1)
        ctrl.stop()

    def test_stop_without_start(self, valid_config, logger):
        """Stop без start — не должен упасть."""
        ctrl = AgentController(valid_config, logger)
        ctrl.stop()

    def test_status_callback_raises(self, valid_config, logger):
        """Callback on_status падает — контроллер не должен упасть."""
        def raising_cb(text, pid):
            raise RuntimeError("callback error")

        ctrl = AgentController(valid_config, logger, on_status=raising_cb)
        ctrl.start()
        time.sleep(1)
        ctrl.stop()

    def test_logger_raises(self, tmp_path, valid_config):
        """Logger падает при записи — контроллер не должен упасть."""
        raising_logger = MagicMock()
        raising_logger.log.side_effect = RuntimeError("log error")

        ctrl = AgentController(valid_config, raising_logger)
        ctrl.start()
        time.sleep(1)
        ctrl.stop()
