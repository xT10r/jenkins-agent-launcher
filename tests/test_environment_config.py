"""Тесты секции environment в config.json."""

import json

from src.config import DEFAULT_IGNORED_ENV_VARS, resolve_config
from src.process import AgentProcess

TEST_VALUE = "test-value"


class TestEnvironmentConfig:
    def test_defaults_include_builtin_ignored_vars(self, tmp_path):
        cfg, errors = resolve_config(tmp_path, {
            "jenkins_url": "https://ok.com",
            "agent_name": "agent",
            "secret": (TEST_VALUE),
        })

        assert not errors
        assert [item.name for item in cfg.environment.ignored_vars] == [
            item["name"] for item in DEFAULT_IGNORED_ENV_VARS
        ]

    def test_custom_ignored_vars_override_defaults(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {
                "jenkinsUrl": "https://ok.com",
                "agentName": "agent",
                "secret": (TEST_VALUE),
            },
            "environment": {
                "ignoredVars": [
                    {
                        "name": "CUSTOM_SECRET",
                        "reason": "Не передавать секрет дочернему процессу.",
                    },
                    "CUSTOM_TOKEN",
                ]
            },
        }), encoding="utf-8")

        cfg, errors = resolve_config(tmp_path)
        assert not errors
        assert [item.name for item in cfg.environment.ignored_vars] == [
            "CUSTOM_SECRET",
            "CUSTOM_TOKEN",
        ]
        assert cfg.environment.ignored_vars[0].reason == "Не передавать секрет дочернему процессу."

    def test_empty_ignored_var_name_is_rejected(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {
                "jenkinsUrl": "https://ok.com",
                "agentName": "agent",
                "secret": (TEST_VALUE),
            },
            "environment": {
                "ignoredVars": [
                    {"name": "", "reason": "broken"},
                ]
            },
        }), encoding="utf-8")

        cfg, errors = resolve_config(tmp_path)
        assert cfg is not None
        assert any("environment.ignoredVars" in e for e in errors)

    def test_duplicate_ignored_var_name_is_rejected(self, tmp_path):
        (tmp_path / "config.json").write_text(json.dumps({
            "agent": {
                "jenkinsUrl": "https://ok.com",
                "agentName": "agent",
                "secret": (TEST_VALUE),
            },
            "environment": {
                "ignoredVars": [
                    "SECRET_A",
                    {"name": "SECRET_A", "reason": "dup"},
                ]
            },
        }), encoding="utf-8")

        cfg, errors = resolve_config(tmp_path)
        assert cfg is not None
        assert any("дубликат" in e for e in errors)

    def test_process_uses_custom_isolated_vars(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CUSTOM_SECRET", TEST_VALUE)
        monkeypatch.setenv("VISIBLE_VAR", "visible")

        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
            isolated_vars=("CUSTOM_SECRET",),
        )

        env = proc._isolated_env()
        assert "CUSTOM_SECRET" not in env
        assert env["VISIBLE_VAR"] == "visible"
