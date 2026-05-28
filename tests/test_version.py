"""Тесты runtime-версии приложения."""

import json
import sys
import types

from src.version import DEFAULT_APP_VERSION, get_app_version


class TestAppVersion:
    def test_reads_version_from_build_json(self, tmp_path):
        build_json = tmp_path / "config" / "build.json"
        build_json.parent.mkdir(parents=True, exist_ok=True)
        build_json.write_text(json.dumps({"version": "3.2.1.4"}), encoding="utf-8")

        assert get_app_version(tmp_path) == "3.2.1.4"

    def test_returns_default_when_build_json_missing(self, tmp_path):
        assert get_app_version(tmp_path) == DEFAULT_APP_VERSION

    def test_returns_default_when_build_json_is_broken(self, tmp_path):
        build_json = tmp_path / "config" / "build.json"
        build_json.parent.mkdir(parents=True, exist_ok=True)
        build_json.write_text("{broken", encoding="utf-8")

        assert get_app_version(tmp_path) == DEFAULT_APP_VERSION

    def test_uses_embedded_build_info_when_build_json_missing(self, tmp_path, monkeypatch):
        module = types.ModuleType("src._build_info")
        module.BUILD_INFO = {"version": "4.5.6.7"}
        monkeypatch.setitem(sys.modules, "src._build_info", module)

        assert get_app_version(tmp_path) == "4.5.6.7"

    def test_build_json_takes_precedence_over_embedded_build_info(self, tmp_path, monkeypatch):
        module = types.ModuleType("src._build_info")
        module.BUILD_INFO = {"version": "4.5.6.7"}
        monkeypatch.setitem(sys.modules, "src._build_info", module)

        build_json = tmp_path / "config" / "build.json"
        build_json.parent.mkdir(parents=True, exist_ok=True)
        build_json.write_text(json.dumps({"version": "8.9.10.11"}), encoding="utf-8")

        assert get_app_version(tmp_path) == "8.9.10.11"
