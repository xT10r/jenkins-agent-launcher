"""Тесты генерации build metadata для packaged-приложения."""

import json
import subprocess
import sys
from pathlib import Path


def test_gen_version_embeds_build_info(tmp_path):
    project = tmp_path
    src_dir = project / "src"
    config_dir = project / "config"
    output_dir = project / "build"
    src_dir.mkdir()
    config_dir.mkdir()
    build_json = config_dir / "build.json"
    build_json.write_text(
        json.dumps(
            {
                "outputExe": "agent-launcher-test.exe",
                "version": "9.8.7.6",
                "title": "Jenkins Agent Launcher",
                "company": "Jenkins Agent Launcher Contributors",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/_gen_version.py", str(build_json), str(output_dir)],
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    runtime_info = src_dir / "_build_info.py"
    assert runtime_info.exists()
    assert "'version': '9.8.7.6'" in runtime_info.read_text(encoding="utf-8")
    vars_text = (output_dir / "_build_vars.bat").read_text(encoding="utf-8")
    assert 'set "OUTPUT_EXE=agent-launcher-test.exe"' in vars_text
    assert 'set "EXE_NAME=agent-launcher-test"' in vars_text
    assert 'set "RUNTIME_INFO=' in vars_text
    vars_json = json.loads((output_dir / "_build_vars.json").read_text(encoding="utf-8"))
    assert vars_json["outputExe"] == "agent-launcher-test.exe"
    assert vars_json["exeName"] == "agent-launcher-test"


def test_gen_version_fails_when_configured_icon_is_missing(tmp_path):
    project = tmp_path
    (project / "src").mkdir()
    config_dir = project / "config"
    output_dir = project / "build"
    config_dir.mkdir()
    build_json = config_dir / "build.json"
    build_json.write_text(
        json.dumps(
            {
                "outputExe": "agent-launcher.exe",
                "iconPath": "assets/missing.ico",
                "version": "9.8.7.6",
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "scripts/_gen_version.py", str(build_json), str(output_dir)],
        check=False,
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "iconPath not found" in result.stdout
