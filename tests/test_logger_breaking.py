"""Ломающие тесты модуля logger."""

import datetime
import os
import threading
import time
from pathlib import Path

import pytest

from src.logger import RotatingLogger, LogConfig


class TestConcurrentWrites:
    """Одновременная запись из множества потоков."""

    def test_100_threads(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        errors = []

        def worker(i):
            try:
                for j in range(100):
                    logger.log(f"thread-{i}-{j}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        logger.close()

        assert not errors, f"Errors during concurrent writes: {errors}"

    def test_rapid_open_close(self, tmp_path):
        """Быстрое открытие/закрытие."""
        for _ in range(500):
            logger = RotatingLogger(tmp_path)
            logger.log("rapid")
            logger.close()


class TestLargeLogs:
    """Огромные логи."""

    def test_10mb_write(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        # 10MB записей
        big_msg = "x" * 10000
        for _ in range(1000):
            logger.log(big_msg)
        logger.close()

        log_file = tmp_path / "logs" / f"jenkins-agent-{datetime.date.today()}.log"
        # Найти любой файл лога
        log_files = list((tmp_path / "logs").glob("jenkins-agent*.log"))
        assert log_files
        total_size = sum(f.stat().st_size for f in log_files)
        assert total_size > 5_000_000  # хотя бы 5MB

    def test_size_rotation_under_load(self, tmp_path):
        logger = RotatingLogger(tmp_path, config=LogConfig(rotation="size", max_size_mb=1))
        for i in range(5000):
            logger.log(f"msg-{i}" * 1000)
        logger.close()

        files = list((tmp_path / "logs").glob("jenkins-agent*.log"))
        # Должен быть хотя бы 1 файл
        assert len(files) >= 1
        # И общий размер > 1MB
        total_size = sum(f.stat().st_size for f in files)
        assert total_size > 1_000_000


class TestDiskFull:
    """Имитация нехватки места на диске."""

    def test_readonly_dir(self, tmp_path):
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        # Сделать директорию readonly
        if os.name == "nt":
            import subprocess
            subprocess.run(["icacls", str(log_dir), "/deny", "Everyone:W"], capture_output=True)
        else:
            os.chmod(log_dir, 0o444)

        logger = RotatingLogger(tmp_path)
        # Не должно упасть
        logger.log("should not crash")
        logger.close()

        # Restore
        if os.name == "nt":
            import subprocess
            subprocess.run(["icacls", str(log_dir), "/grant", "Everyone:W"], capture_output=True)
        else:
            os.chmod(log_dir, 0o755)


class TestInvalidRotation:
    """Недопустимые значения rotation."""

    def test_unknown_rotation(self, tmp_path):
        logger = RotatingLogger(tmp_path, config=LogConfig(rotation="unknown_value"))
        logger.log("test")
        logger.close()
        # Должно работать с fallback на .log
        files = list((tmp_path / "logs").glob("*.log"))
        assert files


class TestUnicodeLogs:
    """Юникод и спецсимволы в логах."""

    def test_emoji(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        logger.log("🚀 Rocket 🎉 Party 🔥 Fire")
        logger.close()
        files = list((tmp_path / "logs").glob("*.log"))
        assert files
        content = files[0].read_text(encoding="utf-8")
        assert "Rocket Party Fire" in content
        assert "🚀" not in content

    def test_cjk(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        logger.log("日本語テスト 中文测试 한국어 테스트")
        logger.close()
        files = list((tmp_path / "logs").glob("*.log"))
        content = files[0].read_text(encoding="utf-8")
        assert "日本語" in content

    def test_null_bytes(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        logger.log("test\x00null\x00bytes")
        logger.close()
        files = list((tmp_path / "logs").glob("*.log"))
        content = files[0].read_text(encoding="utf-8")
        assert "\x00" not in content
        assert "testnullbytes" in content

    def test_newlines_in_message(self, tmp_path):
        logger = RotatingLogger(tmp_path)
        logger.log("line1\nline2\r\nline3")
        logger.close()
        files = list((tmp_path / "logs").glob("*.log"))
        content = files[0].read_text(encoding="utf-8")
        # Переносы строк должны быть экранированы
        assert "line1 | line2 | line3" in content
