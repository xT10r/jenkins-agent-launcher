"""Тесты модуля process."""

import os
import sys
import time
import pytest
from pathlib import Path

from src.process import AgentProcess, ProcessSnapshot, resolve_java_command

TEST_VALUE = "test-value"


class TestProcess:
    def test_resolve_java_from_path_before_java_home(self, monkeypatch):
        monkeypatch.setattr("src.process.shutil.which", lambda name: "/path/java.exe")

        java_cmd, source = resolve_java_command("", env={"JAVA_HOME": "/jdk"})

        assert java_cmd == "/path/java.exe"
        assert source == "PATH"

    def test_resolve_java_from_java_home_when_path_missing(self, tmp_path, monkeypatch):
        java_exe = tmp_path / "jdk" / "bin" / "java.exe"
        java_exe.parent.mkdir(parents=True)
        java_exe.write_text("", encoding="utf-8")
        monkeypatch.setattr("src.process.shutil.which", lambda name: None)

        java_cmd, source = resolve_java_command("", env={"JAVA_HOME": str(tmp_path / "jdk")})

        assert java_cmd == str(java_exe)
        assert source == "JAVA_HOME"

    def test_invalid_configured_java_home_does_not_fallback(self, tmp_path, monkeypatch):
        valid_java = tmp_path / "jdk" / "bin" / "java.exe"
        valid_java.parent.mkdir(parents=True)
        valid_java.write_text("", encoding="utf-8")
        monkeypatch.setattr("src.process.shutil.which", lambda name: str(valid_java))

        java_cmd, source = resolve_java_command(str(tmp_path / "missing-jdk"))

        assert java_cmd is None
        assert "Указанный путь Java не найден" in source

    def test_start_python_echo(self):
        """Запустить python -c "print('hello')" вместо java."""
        lines = []
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar=sys.executable,  # используем python вместо java для теста
            agent_name="test",
            workdir=str(Path.home()),
            secret=(TEST_VALUE),
        )
        # Это упадёт т.к. python - не jar, но PID должен быть получен
        # Для реального теста нужен mock java

    def test_java_not_found(self, monkeypatch):
        """Если java нет — start вернёт None."""
        monkeypatch.setattr("src.process.shutil.which", lambda name: None)
        monkeypatch.delenv("JAVA_HOME", raising=False)

        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(Path.home()),
            secret=(TEST_VALUE),
        )
        assert proc.start() is None

    def test_env_isolation(self, tmp_path):
        """Проверить что JENKINS_* переменные удалены."""
        os.environ["JENKINS_SECRET"] = TEST_VALUE
        try:
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

    def test_secret_file_cleanup(self, tmp_path):
        """Секрет-файл должен быть удалён после cleanup."""
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        proc._create_secret_file()
        secret_file = proc._secret_file
        assert os.path.isfile(secret_file)

        proc.cleanup()
        assert not os.path.isfile(secret_file)

    def test_java_opts_are_added_to_command(self, tmp_path):
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
            java_opts='-Xmx512m "-Djenkins.launcher.mode=gui"',
        )
        cmd = proc._build_cmd("java", "@secret-file")

        assert cmd[0] == "java"
        assert "-Xmx512m" in cmd
        assert "-Djenkins.launcher.mode=gui" in cmd
        assert "-Djenkins.launcher.role=agent-child" in cmd
        assert "-Djenkins.launcher.agentName=test" in cmd
        assert any(item.startswith("-Djenkins.launcher.parentPid=") for item in cmd)
        assert f"-Djenkins.launcher.signature={proc.launch_signature}" in cmd

    def test_stop_terminates_then_kills_when_needed(self, tmp_path):
        events = []

        class DummyProc:
            def __init__(self):
                self.returncode = None

            def poll(self):
                return self.returncode

            def terminate(self):
                events.append("terminate")

            def kill(self):
                events.append("kill")
                self.returncode = 9

            def wait(self, timeout=None):
                events.append(f"wait:{timeout}")
                if len([item for item in events if item.startswith("wait:")]) == 1:
                    raise __import__("subprocess").TimeoutExpired(cmd="java", timeout=timeout)
                return self.returncode

        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar="/tmp/test.jar",
            agent_name="test",
            workdir=str(tmp_path),
            secret=(TEST_VALUE),
        )
        proc._proc = DummyProc()
        proc._owns_process = True

        code = proc.stop(terminate_timeout=0.1, kill_timeout=0.1)

        assert code == 9
        assert events == ["terminate", "wait:0.1", "kill", "wait:0.1"]

    def test_matching_process_found_by_signature(self, tmp_path):
        proc = AgentProcess(
            jenkins_url="https://example.com/",
            agent_jar=str(tmp_path / "agent.jar"),
            agent_name="test",
            workdir=str(tmp_path / "work"),
            secret=TEST_VALUE,  # pragma: allowlist secret  # nosemgrep
        )
        snapshot = ProcessSnapshot(
            pid=4321,
            name="java.exe",
            command_line=" ".join(
                [
                    "java",
                    "-Djenkins.launcher.role=agent-child",
                    f"-Djenkins.launcher.signature={proc.launch_signature}",
                    "-jar",
                    str(tmp_path / "agent.jar"),
                    "-url",
                    "https://example.com/",
                    "-secret",
                    "@secret-file",
                    "-name",
                    "test",
                    "-workDir",
                    str(tmp_path / "work"),
                ]
            ),
        )

        match = proc.find_matching_process([snapshot])

        assert match.status == "matched"
        assert match.process == snapshot

    def test_matching_process_rejects_partial_match(self, tmp_path):
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar=str(tmp_path / "agent.jar"),
            agent_name="test",
            workdir=str(tmp_path / "work"),
            secret=TEST_VALUE,  # pragma: allowlist secret  # nosemgrep
            tunnel="proxy:50000",
        )
        snapshot = ProcessSnapshot(
            pid=4321,
            name="java.exe",
            command_line=" ".join(
                [
                    "java",
                    "-Djenkins.launcher.role=agent-child",
                    "-jar",
                    str(tmp_path / "agent.jar"),
                    "-url",
                    "https://example.com",
                    "-secret",
                    "@secret-file",
                    "-name",
                    "test",
                    "-workDir",
                    str(tmp_path / "work"),
                ]
            ),
        )

        match = proc.find_matching_process([snapshot])

        assert match.status == "not_found"

    def test_matching_process_detects_ambiguity(self, tmp_path):
        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar=str(tmp_path / "agent.jar"),
            agent_name="test",
            workdir=str(tmp_path / "work"),
            secret=TEST_VALUE,  # pragma: allowlist secret  # nosemgrep
        )
        command_line = " ".join(
            [
                "java",
                "-Djenkins.launcher.role=agent-child",
                f"-Djenkins.launcher.signature={proc.launch_signature}",
                "-jar",
                str(tmp_path / "agent.jar"),
                "-url",
                "https://example.com",
                "-secret",
                "@secret-file",
                "-name",
                "test",
                "-workDir",
                str(tmp_path / "work"),
            ]
        )
        candidates = [
            ProcessSnapshot(pid=4321, name="java.exe", command_line=command_line),
            ProcessSnapshot(pid=9876, name="java.exe", command_line=command_line),
        ]

        match = proc.find_matching_process(candidates)

        assert match.status == "ambiguous"
        assert [item.pid for item in match.candidates] == [4321, 9876]

    def test_attached_process_is_not_killed_on_stop(self, tmp_path):
        terminated = []

        proc = AgentProcess(
            jenkins_url="https://example.com",
            agent_jar=str(tmp_path / "agent.jar"),
            agent_name="test",
            workdir=str(tmp_path / "work"),
            secret=TEST_VALUE,  # pragma: allowlist secret  # nosemgrep
        )

        proc.attach(ProcessSnapshot(pid=2222, name="java.exe", command_line="java"))
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr("src.process._terminate_pid", lambda pid: terminated.append(pid))
        monkeypatch.setattr("src.process._kill_pid", lambda pid: (_ for _ in ()).throw(AssertionError("kill not expected")))
        monkeypatch.setattr("src.process._pid_is_running", lambda pid: len(terminated) == 0)

        try:
            assert proc.owns_process is False
            assert proc.stop(terminate_timeout=0.1, kill_timeout=0.1) == 0
            assert terminated == [2222]
        finally:
            monkeypatch.undo()
