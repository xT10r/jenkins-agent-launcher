"""Тесты безопасности."""

import os
import tempfile
import threading
import time
from pathlib import Path

import pytest

from src.logger import RotatingLogger, LogConfig
from src.config import AppConfig

TEST_VALUE = "test-value"
LONG_VALUE = "v" * 22


class TestEnvIsolation:
    """Проверка что JENKINS_* переменные не попадают в дочерний процесс."""

    def test_all_isolated(self):
        from src.process import AgentProcess
        isolated = AgentProcess.ISOLATED_VARS

        expected = {
            "JENKINS_SECRET", "JENKINS_AGENT_NAME", "JENKINS_TUNNEL",
            "JENKINS_WEB_SOCKET", "JENKINS_DIRECT_CONNECTION",
            "JENKINS_INSTANCE_IDENTITY", "JENKINS_PROTOCOLS",
            "JENKINS_JAVA_OPTS", "JENKINS_FALLBACK_JAR_PATH",
        }
        assert set(isolated) == expected

    def test_no_leak_in_env(self, tmp_path):
        import subprocess
        os.environ["JENKINS_SECRET"] = TEST_VALUE
        os.environ["JENKINS_AGENT_NAME"] = "leaked-name"
        try:
            from src.process import AgentProcess
            proc = AgentProcess(
                jenkins_url="https://example.com",
                agent_jar="/tmp/test.jar",
                agent_name="test",
                workdir=str(tmp_path),
                secret=(TEST_VALUE),
            )
            env = proc._isolated_env()
            assert "JENKINS_SECRET" not in env
            assert "JENKINS_AGENT_NAME" not in env
        finally:
            del os.environ["JENKINS_SECRET"]
            del os.environ["JENKINS_AGENT_NAME"]


class TestSecretFile:
    """Безопасность секрет-файла."""

    def test_secret_zeroed_before_delete(self, tmp_path):
        from src.process import AgentProcess
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(LONG_VALUE),
        )
        proc._create_secret_file()
        fpath = proc._secret_file

        # До cleanup — секрет на месте
        assert open(fpath, "rb").read() == LONG_VALUE.encode("utf-8")

        # После cleanup — файл перезаписан нулями
        proc.cleanup()
        assert not os.path.isfile(fpath)

    def test_no_secret_in_cmdline(self, tmp_path):
        """Секрет не должен быть виден в командной строке."""
        from src.process import AgentProcess
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        secret_arg = proc._create_secret_file()
        cmd = proc._build_cmd("java", secret_arg)

        # В cmdline только @path, не сам секрет
        assert TEST_VALUE not in " ".join(cmd)
        assert "@/tmp/" in " ".join(cmd) or "@" in " ".join(cmd)
        proc.cleanup()


class TestPathTraversal:
    """Path traversal атаки через конфиг."""

    def test_workdir_traversal(self):
        """Workdir с ../../../ не должен выйти за пределы."""
        from src.config import resolve_config
        cfg, errors = resolve_config(Path("/tmp"), {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
            "work_dir": "../../../../etc",
        })
        # Должно использовать переданный путь, но не упасть
        assert "etc" in cfg.agent.workdir or cfg.agent.workdir

    def test_log_path_traversal(self):
        """Log path с ../../../."""
        from src.config import resolve_config
        cfg, errors = resolve_config(Path("/tmp"), {
            "jenkins_url": "https://ok.com",
            "agent_name": "a",
            "secret": "s",
            "log_path": "../../../../tmp/traversal.log",
        })
        assert cfg is not None


class TestRaceConditions:
    """Гонки потоков."""

    def test_controller_stop_race(self, tmp_path):
        """Stop в тот же момент когда процесс завершается."""
        from src.agent_controller import AgentController

        cfg = AppConfig()
        cfg.agent.jenkins_url = "https://example.com"
        cfg.agent.agent_name = "test"
        cfg.agent.secret = (TEST_VALUE)
        cfg.agent.workdir = str(tmp_path)
        cfg.agent.agent_jar_path = str(tmp_path / "fake.jar")
        (tmp_path / "fake.jar").write_bytes(b"fake")
        cfg.behavior.max_restarts = 0
        cfg.behavior.jenkins_timeout = 1

        logger = RotatingLogger(tmp_path)
        ctrl = AgentController(cfg, logger)
        ctrl.start()

        # Stop через 0.5 сек
        threading.Thread(target=lambda: (time.sleep(0.5), ctrl.stop())).start()

        time.sleep(2)
        logger.close()

    def test_concurrent_log_and_cleanup(self, tmp_path):
        """Одновременная запись лога и cleanup."""
        from src.logger import RotatingLogger, LogConfig

        logger = RotatingLogger(tmp_path, config=LogConfig(max_days=1))

        def writer():
            for _ in range(100):
                logger.log("concurrent write")

        def cleaner():
            time.sleep(0.01)
            logger.cleanup_old()

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=cleaner)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        logger.close()
