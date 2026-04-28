"""Тесты защиты от дублирующихся экземпляров."""

import json
import os

from src.config import AppConfig
from src.instance_guard import ConfigInstanceGuard


def _make_config(tmp_path, agent_name="agent-1", jenkins_url="https://jenkins.example.com"):
    cfg = AppConfig()
    cfg.agent.jenkins_url = jenkins_url
    cfg.agent.agent_name = agent_name
    cfg.agent.secret = "secret"  # pragma: allowlist secret
    cfg.agent.workdir = str(tmp_path / "work")
    cfg.agent.agent_jar_path = str(tmp_path / "agent.jar")
    return cfg


class TestInstanceGuard:
    def test_acquire_and_release(self, tmp_path):
        cfg = _make_config(tmp_path)
        guard = ConfigInstanceGuard(cfg, root_dir=tmp_path / "locks")

        acquired, message = guard.acquire()

        assert acquired is True
        assert message is None
        assert guard.path.exists()

        guard.release()
        assert not guard.path.exists()

    def test_duplicate_live_pid_is_rejected(self, tmp_path):
        cfg = _make_config(tmp_path)
        guard = ConfigInstanceGuard(cfg, root_dir=tmp_path / "locks")
        guard.path.parent.mkdir(parents=True, exist_ok=True)
        guard.path.write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        acquired, message = guard.acquire()

        assert acquired is False
        assert "Уже запущен экземпляр" in message

    def test_stale_lock_is_replaced(self, tmp_path, monkeypatch):
        cfg = _make_config(tmp_path)
        guard = ConfigInstanceGuard(cfg, root_dir=tmp_path / "locks")
        guard.path.parent.mkdir(parents=True, exist_ok=True)
        guard.path.write_text(json.dumps({"pid": 999999}), encoding="utf-8")
        monkeypatch.setattr("src.instance_guard._is_process_alive", lambda pid: False)

        acquired, message = guard.acquire()

        assert acquired is True
        assert message is None
        guard.release()
