"""
Управление java-процессом: запуск, изоляция ENV, мониторинг.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import ctypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


def _java_binary_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("java.exe", "java")
    return ("java",)


def _java_process_names() -> tuple[str, ...]:
    if os.name == "nt":
        return ("java.exe", "javaw.exe", "java")
    return ("java", "javaw")


def _normalize_url(value: str) -> str:
    return str(value).strip().rstrip("/").lower()


def _normalize_path(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        return ""
    expanded = str(Path(os.path.expandvars(raw)).expanduser())
    if os.name == "nt":
        return expanded.replace("/", "\\").lower()
    return expanded


def build_launch_signature(
    *,
    jenkins_url: str,
    agent_jar: str,
    agent_name: str,
    workdir: str = "",
    tunnel: str = "",
    websocket: bool = False,
    direct: str = "",
    instance_identity: str = "",
    protocols: str = "",
) -> str:
    payload = {
        "jenkins_url": _normalize_url(jenkins_url),
        "agent_jar": _normalize_path(agent_jar),
        "agent_name": str(agent_name).strip(),
        "workdir": _normalize_path(workdir),
        "tunnel": str(tunnel).strip(),
        "websocket": bool(websocket),
        "direct": str(direct).strip(),
        "instance_identity": str(instance_identity).strip(),
        "protocols": str(protocols).strip(),
    }
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


@dataclass(frozen=True)
class ProcessSnapshot:
    pid: int
    name: str
    command_line: str

    @property
    def args(self) -> list[str]:
        return _split_command_line(self.command_line)


@dataclass(frozen=True)
class ProcessMatchResult:
    status: str
    process: ProcessSnapshot | None = None
    candidates: tuple[ProcessSnapshot, ...] = ()


def _split_command_line(command_line: str) -> list[str]:
    if not command_line.strip():
        return []

    parsers = [lambda: shlex.split(command_line, posix=(os.name != "nt"))]
    if os.name == "nt":
        parsers.append(lambda: shlex.split(command_line, posix=False))

    for parser in parsers:
        try:
            return parser()
        except ValueError:
            continue

    return command_line.split()


def _parse_agent_arguments(args: list[str]) -> dict[str, str | bool]:
    parsed: dict[str, str | bool] = {}
    options_with_values = {
        "-jar",
        "-url",
        "-secret",
        "-name",
        "-workDir",
        "-tunnel",
        "-direct",
        "-instanceIdentity",
        "-protocols",
    }
    i = 0
    while i < len(args):
        item = args[i]
        if item.startswith("-Djenkins.launcher.signature="):
            parsed["launcher_signature"] = item.split("=", 1)[1]
        elif item == "-Djenkins.launcher.role=agent-child":
            parsed["launcher_role"] = "agent-child"
        elif item in options_with_values and i + 1 < len(args):
            parsed[item] = args[i + 1]
            i += 1
        elif item == "-webSocket":
            parsed[item] = True
        i += 1
    return parsed


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False

    if os.name == "nt":
        return _pid_is_running_windows(pid)

    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_is_running_windows(pid: int) -> bool:
    process_query_limited_information = 0x1000
    synchronize = 0x00100000
    still_active = 259

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        process_query_limited_information | synchronize,
        False,
        int(pid),
    )
    if not handle:
        return False

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return

    if os.name == "nt":
        _kill_pid_windows(pid)
        return

    os.kill(pid, signal.SIGTERM)


def _kill_pid(pid: int) -> None:
    if pid <= 0:
        return

    if os.name == "nt":
        _kill_pid_windows(pid)
        return

    os.kill(pid, signal.SIGKILL)


def _kill_pid_windows(pid: int) -> None:
    process_terminate = 0x0001

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(process_terminate, False, int(pid))
    if not handle:
        raise OSError(f"Не удалось открыть процесс для завершения: PID {pid}")

    try:
        if not kernel32.TerminateProcess(handle, 1):
            raise OSError(f"Не удалось завершить процесс: PID {pid}")
    finally:
        kernel32.CloseHandle(handle)


def _list_java_processes_windows() -> list[ProcessSnapshot]:
    command = (
        "$ErrorActionPreference='Stop'; "
        "$items = Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -in @('java.exe','javaw.exe','java') } | "
        "Select-Object ProcessId, Name, CommandLine; "
        "$items | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    raw = completed.stdout.strip()
    if not raw:
        return []

    payload = json.loads(raw)
    if isinstance(payload, dict):
        payload = [payload]

    processes: list[ProcessSnapshot] = []
    for item in payload:
        try:
            processes.append(
                ProcessSnapshot(
                    pid=int(item.get("ProcessId") or 0),
                    name=str(item.get("Name") or ""),
                    command_line=str(item.get("CommandLine") or ""),
                )
            )
        except Exception:
            continue
    return processes


def _list_java_processes_posix() -> list[ProcessSnapshot]:
    completed = subprocess.run(
        ["ps", "-eo", "pid=,comm=,args="],
        check=True,
        capture_output=True,
        text=True,
    )
    processes: list[ProcessSnapshot] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid_raw, name, command_line = parts
        if name not in _java_process_names():
            continue
        try:
            processes.append(
                ProcessSnapshot(
                    pid=int(pid_raw),
                    name=name,
                    command_line=command_line,
                )
            )
        except ValueError:
            continue
    return processes


def list_java_processes() -> list[ProcessSnapshot]:
    try:
        if os.name == "nt":
            return _list_java_processes_windows()
        return _list_java_processes_posix()
    except Exception:
        return []


def _resolve_java_from_location(location: str) -> str | None:
    raw = str(location).strip()
    if not raw:
        return None

    candidate = Path(os.path.expandvars(raw)).expanduser()
    search_paths: list[Path] = []

    if candidate.is_file():
        search_paths.append(candidate)
    elif candidate.is_dir():
        for binary_name in _java_binary_names():
            search_paths.append(candidate / binary_name)
            search_paths.append(candidate / "bin" / binary_name)

    for path in search_paths:
        if path.is_file():
            return str(path.resolve(strict=False))

    return None


def resolve_java_command(
    configured_java_home: str = "",
    env: dict[str, str] | None = None,
) -> tuple[str | None, str]:
    """
    Найти java для запуска.

    Приоритет:
    1. Явно заданный путь/корень JDK (`agent.javaHome`, `--java-home`)
    2. `java` из PATH
    3. `JAVA_HOME`
    """
    if configured_java_home.strip():
        resolved = _resolve_java_from_location(configured_java_home)
        if resolved:
            return resolved, "configured"
        return None, f"Указанный путь Java не найден: {configured_java_home}"

    from_path = shutil.which("java")
    if from_path:
        return from_path, "PATH"

    env = env or os.environ
    java_home = str(env.get("JAVA_HOME") or "").strip()
    if java_home:
        resolved = _resolve_java_from_location(java_home)
        if resolved:
            return resolved, "JAVA_HOME"
        return None, f"JAVA_HOME указывает на недоступный путь Java: {java_home}"

    return None, "Java не найдена: укажите agent.javaHome/--java-home, добавьте java в PATH или задайте JAVA_HOME"


class AgentProcess:
    """Запуск и управление процессом Jenkins-агента."""

    ISOLATED_VARS = (
        "JENKINS_SECRET", "JENKINS_AGENT_NAME", "JENKINS_TUNNEL",
        "JENKINS_WEB_SOCKET", "JENKINS_DIRECT_CONNECTION",
        "JENKINS_INSTANCE_IDENTITY", "JENKINS_PROTOCOLS",
        "JENKINS_JAVA_OPTS", "JENKINS_FALLBACK_JAR_PATH",
    )

    def __init__(
        self,
        jenkins_url: str,
        agent_jar: str,
        agent_name: str,
        workdir: str,
        secret: str,
        tunnel: str = "",
        websocket: bool = False,
        direct: str = "",
        instance_identity: str = "",
        protocols: str = "",
        java_opts: str = "",
        java_home: str = "",
        java_cmd: str = "",
        isolated_vars: Iterable[str] | None = None,
        on_line: Callable[[str], None] | None = None,
    ):
        self.jenkins_url = jenkins_url
        self.agent_jar = agent_jar
        self.agent_name = agent_name
        self.workdir = workdir
        self.secret = secret
        self.tunnel = tunnel
        self.websocket = websocket
        self.direct = direct
        self.instance_identity = instance_identity
        self.protocols = protocols
        self.java_opts = java_opts
        self.java_home = java_home
        self.java_cmd = java_cmd
        self.isolated_vars = tuple(isolated_vars or self.ISOLATED_VARS)
        self.on_line = on_line

        self._proc: subprocess.Popen | None = None
        self._secret_file: str | None = None
        self._attached_pid: int | None = None
        self._owns_process = False
        self._attached_command_line = ""

    # ── Public ──

    @property
    def launch_signature(self) -> str:
        return build_launch_signature(
            jenkins_url=self.jenkins_url,
            agent_jar=self.agent_jar,
            agent_name=self.agent_name,
            workdir=self.workdir,
            tunnel=self.tunnel,
            websocket=self.websocket,
            direct=self.direct,
            instance_identity=self.instance_identity,
            protocols=self.protocols,
        )

    @property
    def pid(self) -> int | None:
        if self._proc is not None:
            return self._proc.pid
        return self._attached_pid

    @property
    def owns_process(self) -> bool:
        return self._owns_process

    def start(self) -> int | None:
        """
        Запустить процесс. Возвращает PID или None при ошибке.
        """
        java, _ = resolve_java_command(self.java_home) if not self.java_cmd else (self.java_cmd, "pre-resolved")
        if not java:
            return None

        secret_arg = self._create_secret_file()
        cmd = self._build_cmd(java, secret_arg)
        env = self._isolated_env()

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            cwd=self._resolve_cwd(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self._attached_pid = None
        self._attached_command_line = ""
        self._owns_process = True

        # Поток чтения stdout
        threading.Thread(target=self._reader, daemon=True).start()
        return self._proc.pid

    def attach(self, snapshot: ProcessSnapshot) -> int:
        self._proc = None
        self._attached_pid = snapshot.pid
        self._attached_command_line = snapshot.command_line
        self._owns_process = False
        return snapshot.pid

    def find_matching_process(
        self,
        candidates: Iterable[ProcessSnapshot] | None = None,
    ) -> ProcessMatchResult:
        items = tuple(list_java_processes() if candidates is None else candidates)
        matches = tuple(candidate for candidate in items if self._matches_snapshot(candidate))
        if not matches:
            return ProcessMatchResult(status="not_found", candidates=())
        if len(matches) > 1:
            return ProcessMatchResult(status="ambiguous", candidates=matches)
        return ProcessMatchResult(status="matched", process=matches[0], candidates=matches)

    @property
    def is_running(self) -> bool:
        if self._proc is not None:
            return self._proc.poll() is None
        if self._attached_pid is not None:
            return _pid_is_running(self._attached_pid)
        return False

    def terminate(self):
        if self._owns_process and self._proc and self.is_running:
            self._proc.terminate()
        elif self._attached_pid is not None and self.is_running:
            _terminate_pid(self._attached_pid)

    def kill(self):
        if self._owns_process and self._proc and self.is_running:
            self._proc.kill()
        elif self._attached_pid is not None and self.is_running:
            _kill_pid(self._attached_pid)

    def wait(self, timeout: float | None = None) -> int | None:
        if self._proc:
            try:
                return self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return None
        if self._attached_pid is not None:
            deadline = None if timeout is None else time.monotonic() + timeout
            while self.is_running:
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                time.sleep(0.05)
            return 0
        return None

    def stop(self, terminate_timeout: float = 10.0, kill_timeout: float = 5.0) -> int | None:
        """Корректно завершить процесс: terminate -> wait -> kill."""
        if not self._proc and self._attached_pid is None:
            return None

        if not self.is_running:
            return self.get_returncode()

        self.terminate()
        code = self.wait(timeout=terminate_timeout)
        if code is not None:
            return code

        self.kill()
        return self.wait(timeout=kill_timeout)

    def get_returncode(self) -> int | None:
        if self._proc:
            return self._proc.poll()
        return None

    def cleanup(self):
        """Удалить временный файл секрета."""
        if self._secret_file and os.path.isfile(self._secret_file):
            try:
                sz = os.path.getsize(self._secret_file)
                with open(self._secret_file, "wb") as f:
                    f.write(b"\x00" * sz)
                os.remove(self._secret_file)
            except Exception:
                pass
            finally:
                self._secret_file = None
        elif self._secret_file:
            self._secret_file = None

    # ── Internal ──

    def _build_cmd(self, java: str, secret_arg: str) -> list[str]:
        cmd = [java]
        if self.java_opts:
            cmd += shlex.split(self.java_opts, posix=True)
        cmd += [
            "-Djenkins.launcher.role=agent-child",
            f"-Djenkins.launcher.agentName={self.agent_name}",
            f"-Djenkins.launcher.parentPid={os.getpid()}",
            f"-Djenkins.launcher.signature={self.launch_signature}",
        ]
        cmd += [
            "-jar", self.agent_jar,
            "-url", self.jenkins_url,
            "-secret", secret_arg,
            "-name", self.agent_name,
            "-workDir", self.workdir,
        ]
        if self.tunnel:
            cmd += ["-tunnel", self.tunnel]
        if self.websocket:
            cmd.append("-webSocket")
        if self.direct:
            cmd += ["-direct", self.direct]
        if self.instance_identity:
            cmd += ["-instanceIdentity", self.instance_identity]
        if self.protocols:
            cmd += ["-protocols", self.protocols]
        return cmd

    def _isolated_env(self) -> dict:
        env = os.environ.copy()
        for var in self.isolated_vars:
            env.pop(var, None)
        return env

    def _create_secret_file(self) -> str:
        fd, path = tempfile.mkstemp(prefix="jenkins-secret-", suffix=".tmp")
        try:
            os.write(fd, self.secret.encode("utf-8"))
        finally:
            os.close(fd)
        self._secret_file = path
        return f"@{path}"

    def _resolve_cwd(self) -> str | None:
        candidate_dirs = [
            os.path.dirname(self.agent_jar) if self.agent_jar else "",
            self.workdir,
        ]
        for candidate in candidate_dirs:
            if candidate and os.path.isdir(candidate):
                return candidate
        return None

    def _matches_snapshot(self, snapshot: ProcessSnapshot) -> bool:
        parsed = _parse_agent_arguments(snapshot.args)
        signature = str(parsed.get("launcher_signature") or "").strip()
        if signature and signature == self.launch_signature:
            return True

        if parsed.get("launcher_role") != "agent-child":
            return False

        expected_pairs = {
            "-jar": _normalize_path(self.agent_jar),
            "-url": _normalize_url(self.jenkins_url),
            "-name": self.agent_name.strip(),
            "-workDir": _normalize_path(self.workdir),
            "-tunnel": self.tunnel.strip(),
            "-direct": self.direct.strip(),
            "-instanceIdentity": self.instance_identity.strip(),
            "-protocols": self.protocols.strip(),
        }
        for option, expected in expected_pairs.items():
            actual_raw = parsed.get(option)
            actual = str(actual_raw).strip() if actual_raw is not None else ""
            if option in {"-jar", "-workDir"}:
                actual = _normalize_path(actual)
            elif option == "-url":
                actual = _normalize_url(actual)

            if actual != expected:
                return False

        return bool(parsed.get("-webSocket", False)) is self.websocket

    def _reader(self):
        if not self._proc or not self._proc.stdout:
            return
        for raw in self._proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line and self.on_line:
                try:
                    self.on_line(line)
                except Exception:
                    pass
