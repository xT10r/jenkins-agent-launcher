"""Тесты модуля logger."""

import datetime
import os
import time
from pathlib import Path

import pytest

from src.logger import RotatingLogger, LogConfig


@pytest.fixture
def tmp_proj(tmp_path):
    return tmp_path


@pytest.fixture
def logger(tmp_proj):
    return RotatingLogger(project_dir=tmp_proj)


class TestBasicLogging:
    def test_write_and_read(self, logger, tmp_proj):
        logger.log("test message")
        logger.close()
        log_file = tmp_proj / "logs" / f"jenkins-agent-{datetime.date.today()}.log"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "test_message" in content.replace(" ", "_") or "test message" in content

    def test_tsv_format(self, logger, tmp_proj):
        logger.log("hello", level="WARN", comp="Test")
        logger.close()
        log_file = tmp_proj / "logs" / f"jenkins-agent-{datetime.date.today()}.log"
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2  # header + entry
        parts = lines[1].split("\t")
        assert len(parts) == 4
        assert parts[1] == "WARN"
        assert parts[2] == "Test"

    def test_gui_callback(self, logger):
        received = []
        logger.set_gui_callback(lambda line: received.append(line))
        logger.log("callback test")
        assert len(received) == 1
        assert "callback test" in received[0]

    def test_buffer_flush(self, logger):
        # Логи до установки callback буферизуются
        logger.log("before callback")
        received = []
        logger.set_gui_callback(lambda line: received.append(line))
        assert len(received) >= 1
        assert any("before callback" in r for r in received)


class TestRotation:
    def test_daily_filename(self, tmp_proj):
        logger = RotatingLogger(tmp_proj, config=LogConfig(rotation="daily"))
        path = logger.get_current_path()
        assert datetime.date.today().isoformat() in path
        assert "jenkins-agent" in path

    def test_weekly_filename(self, tmp_proj):
        logger = RotatingLogger(tmp_proj, config=LogConfig(rotation="weekly"))
        path = logger.get_current_path()
        assert "-W" in path
        assert "jenkins-agent" in path

    def test_never_filename(self, tmp_proj):
        logger = RotatingLogger(tmp_proj, config=LogConfig(rotation="never"))
        path = logger.get_current_path()
        assert path.endswith("jenkins-agent.log")

    def test_custom_log_path_is_used(self, tmp_proj):
        custom_path = tmp_proj / "custom-logs" / "agent-runtime.log"
        logger = RotatingLogger(
            tmp_proj,
            config=LogConfig(rotation="never", path=str(custom_path)),
        )
        path = logger.get_current_path()
        assert path.endswith("custom-logs\\agent-runtime.log")

    def test_custom_log_path_keeps_rotation_pattern(self, tmp_proj):
        custom_path = tmp_proj / "custom-logs" / "agent-runtime.log"
        logger = RotatingLogger(
            tmp_proj,
            config=LogConfig(rotation="daily", path=str(custom_path)),
        )
        path = logger.get_current_path()
        assert "agent-runtime-" in path
        assert path.endswith(".log")

    def test_size_rotation(self, tmp_proj):
        logger = RotatingLogger(tmp_proj, config=LogConfig(rotation="size", max_size_mb=1))
        # Записать ~2MB
        for _ in range(300):
            logger.log("x" * 10000)
        logger.close()

        # Должно быть минимум 1 файл (rotation мог оставить 1 rotated + 1 current)
        log_files = list((tmp_proj / "logs").glob("jenkins-agent*.log"))
        # Файл должен существовать
        assert len(log_files) >= 1
        # И должен быть rotated файл (с timestamp)
        rotated = list((tmp_proj / "logs").glob("jenkins-agent-20*.log"))
        assert len(rotated) >= 1


class TestCleanup:
    def test_delete_old_logs(self, tmp_proj):
        log_dir = tmp_proj / "logs"
        log_dir.mkdir()

        # Создать старый файл (30 дней назад)
        old_file = log_dir / "jenkins-agent-2020-01-01.log"
        old_file.write_text("old")
        old_time = (datetime.datetime.now() - datetime.timedelta(days=30)).timestamp()
        os.utime(old_file, (old_time, old_time))

        logger = RotatingLogger(tmp_proj, config=LogConfig(max_days=14))
        logger.cleanup_old()

        assert not old_file.exists()

    def test_keep_recent_logs(self, tmp_proj):
        log_dir = tmp_proj / "logs"
        log_dir.mkdir()

        recent = log_dir / f"jenkins-agent-{datetime.date.today()}.log"
        recent.write_text("recent")

        logger = RotatingLogger(tmp_proj, config=LogConfig(max_days=14))
        logger.cleanup_old()

        assert recent.exists()
