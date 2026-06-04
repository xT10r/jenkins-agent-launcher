"""Тесты модуля main.py (CLI парсинг)."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.main import _parse_args, _cli_to_dict, _resolve_icon_path

TEST_VALUE = "test-value"


class TestParseArgs:
    """Тесты парсинга аргументов командной строки."""

    def test_no_args(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent"])
        args = _parse_args()
        assert not args.test_config
        assert not args.no_gui
        assert args.url is None
        assert args.name is None
        assert args.secret is None
        assert args.tunnel is None
        assert not args.websocket
        assert args.direct is None
        assert args.max_restarts is None
        assert args.restart_delay is None
        assert args.timeout is None

    def test_test_config(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--test-config"])
        args = _parse_args()
        assert args.test_config is True

    def test_no_gui(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--no-gui"])
        args = _parse_args()
        assert args.no_gui is True

    def test_url(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--url", "https://jenkins.example.com"])
        args = _parse_args()
        assert args.url == "https://jenkins.example.com"

    def test_name(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--name", "test-agent"])
        args = _parse_args()
        assert args.name == "test-agent"

    def test_secret(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--secret", TEST_VALUE])
        args = _parse_args()
        assert args.secret == TEST_VALUE

    def test_websocket(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--websocket"])
        args = _parse_args()
        assert args.websocket is True

    def test_tunnel(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--tunnel", "proxy:50000"])
        args = _parse_args()
        assert args.tunnel == "proxy:50000"

    def test_max_restarts(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--max-restarts", "5"])
        args = _parse_args()
        assert args.max_restarts == 5

    def test_max_restarts_negative(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--max-restarts", "-1"])
        args = _parse_args()
        assert args.max_restarts == -1

    def test_restart_delay(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--restart-delay", "10"])
        args = _parse_args()
        assert args.restart_delay == 10

    def test_timeout(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--timeout", "30"])
        args = _parse_args()
        assert args.timeout == 30

    def test_combined_args(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "jenkins-agent",
            "--url", "https://jenkins.example.com",
            "--name", "win-agent",
            "--secret", TEST_VALUE,
            "--tunnel", "proxy:50000",
            "--websocket",
            "--no-gui",
            "--max-restarts", "3",
            "--restart-delay", "10",
            "--timeout", "30",
        ])
        args = _parse_args()
        assert args.url == "https://jenkins.example.com"
        assert args.name == "win-agent"
        assert args.secret == TEST_VALUE
        assert args.tunnel == "proxy:50000"
        assert args.websocket is True
        assert args.no_gui is True
        assert args.max_restarts == 3
        assert args.restart_delay == 10
        assert args.timeout == 30

    def test_no_auto_update(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--no-auto-update"])
        args = _parse_args()
        assert args.no_auto_update is True

    def test_auto_update(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--auto-update"])
        args = _parse_args()
        assert args.auto_update is True

    def test_updated_via_self_update_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--updated-via-self-update"])
        args = _parse_args()
        assert args.updated_via_self_update is True

    def test_update_session_flag(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--update-session", "session.json"])
        args = _parse_args()
        assert args.update_session == "session.json"

    def test_fallback_url(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--fallback-url", "https://downloads.example.com/agent.jar"])
        args = _parse_args()
        assert args.fallback_url == "https://downloads.example.com/agent.jar"

    def test_temp_dir(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--temp-dir", "runtime/tmp"])
        args = _parse_args()
        assert args.temp_dir == "runtime/tmp"


class TestCliToDict:
    """Тесты конвертации Namespace → dict."""

    def test_empty_args(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent"])
        args = _parse_args()
        result = _cli_to_dict(args)
        # Все None/False должны быть отфильтрованы
        assert result == {}

    def test_with_values(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "jenkins-agent", "--url", "https://example.com", "--name", "test"
        ])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert result["jenkins_url"] == "https://example.com"
        assert result["agent_name"] == "test"

    def test_websocket_true(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--websocket"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert result["websocket"] is True

    def test_websocket_false_filtered(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert "websocket" not in result

    def test_no_gui_true(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--no-gui"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert result["no_gui"] is True

    def test_test_config_true(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--test-config"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert result["test_config"] is True

    def test_updated_via_self_update_is_filtered_from_config_dict(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--updated-via-self-update"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert "updated_via_self_update" not in result

    def test_update_session_is_filtered_from_config_dict(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["jenkins-agent", "--update-session", "session.json"])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert "update_session" not in result

    def test_fallback_timeout_and_jar_keys_normalized(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "jenkins-agent",
            "--fallback-url", "https://downloads.example.com/agent.jar",
            "--jar-path", "agent.jar",
            "--temp-dir", "runtime/tmp",
            "--timeout", "45",
        ])
        args = _parse_args()
        result = _cli_to_dict(args)
        assert result["fallback_jar_url"] == "https://downloads.example.com/agent.jar"
        assert result["agent_jar_path"] == "agent.jar"
        assert result["temp_dir"] == "runtime/tmp"
        assert result["jenkins_timeout"] == 45


class TestResolveIconPath:
    def test_uses_project_asset_when_not_frozen(self):
        project_dir = Path.cwd()
        icon = project_dir / "assets" / "jenkins.ico"

        assert _resolve_icon_path(project_dir) == str(icon)

    def test_uses_pyinstaller_bundle_asset_when_frozen(self):
        bundle_dir = Path.cwd()
        bundle_icon = bundle_dir / "assets" / "jenkins.ico"

        assert _resolve_icon_path(
            Path("missing-project-dir"),
            frozen=True,
            bundle_dir=bundle_dir,
        ) == str(bundle_icon)
