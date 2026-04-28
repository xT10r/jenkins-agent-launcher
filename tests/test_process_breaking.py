"""Ломающие тесты модуля process."""

import os
import sys
import threading
import time
import pytest
from pathlib import Path

from src.process import AgentProcess

TEST_VALUE = "test-value"
SPECIAL_VALUE = "sym-value-!@#$%^&*(){}[]|:;'<>,.?/~`"


class TestBrokenProcess:
    """Тесты с некорректными/ломающими параметрами."""

    def test_empty_secret(self, tmp_path):
        """Пустой секрет — должен создать пустой файл."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret="",
        )
        secret_arg = proc._create_secret_file()
        assert secret_arg.startswith("@")
        assert os.path.isfile(secret_arg[1:])
        assert os.path.getsize(secret_arg[1:]) == 0
        proc.cleanup()

    def test_very_long_secret(self, tmp_path):
        """Очень длинный секрет — 10KB."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret="x" * 10000,
        )
        proc._create_secret_file()
        assert os.path.getsize(proc._secret_file) == 10000
        proc.cleanup()

    def test_secret_with_special_chars(self, tmp_path):
        """Секрет с спецсимволами."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(SPECIAL_VALUE),
        )
        proc._create_secret_file()
        content = open(proc._secret_file, "rb").read()
        assert SPECIAL_VALUE.encode("utf-8") in content
        proc.cleanup()

    def test_unicode_workdir(self, tmp_path):
        """Workdir с юникодом."""
        unicode_dir = tmp_path / "тест_директория_🚀"
        unicode_dir.mkdir()
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="тест-агент",
            workdir=str(unicode_dir),
            secret=(TEST_VALUE),
        )
        # Должно создать без ошибок
        assert proc.workdir == str(unicode_dir)

    def test_env_injection_attempt(self, tmp_path):
        """Попытка инъекции через ENV."""
        # Установить переменную с именем похожим на JENKINS_*
        os.environ["JENKINS_SECRET_EXTRA"] = "injected"  # pragma: allowlist secret
        try:
            proc = AgentProcess(
                jenkins_url="https://example.com",
                agent_jar="/tmp/test.jar",
                agent_name="test",
                workdir=str(tmp_path),
                secret=(TEST_VALUE),
            )
            env = proc._isolated_env()
            # Точное совпадение должно быть удалено
            assert "JENKINS_SECRET" not in env
            # Но похожие — остаться
            assert "JENKINS_SECRET_EXTRA" in env
        finally:
            del os.environ["JENKINS_SECRET_EXTRA"]


class TestProcessRace:
    """Гонки при запуске/остановке."""

    def test_rapid_start_stop(self, tmp_path):
        """Быстрый start → terminate."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        # Без java процесс не запустится, но не должен упасть
        pid = proc.start()
        proc.terminate()
        proc.cleanup()

    def test_double_cleanup(self, tmp_path):
        """Двойной cleanup — не должен упасть."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        proc._create_secret_file()
        proc.cleanup()
        proc.cleanup()  # Второй раз — не должен упасть

    def test_cleanup_without_secret(self, tmp_path):
        """Cleanup без создания секрет-файла."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        proc.cleanup()  # Не должен упасть
