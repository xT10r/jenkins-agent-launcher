"""
Production-ready self-update launcher через staging, session-file и внешний helper.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import requests

from .config import UpdateConfig
from .logger import RotatingLogger
from .version import get_app_version

UPDATE_STATES = (
    "idle",
    "checking_update",
    "update_available",
    "staging_update",
    "update_ready",
    "applying_update",
    "restarting_launcher",
    "reattaching_agent",
    "update_completed",
    "update_failed",
    "update_recovered",
)

ALLOWED_TRANSITIONS = {
    "idle": {"checking_update"},
    "checking_update": {"update_available", "update_failed"},
    "update_available": {"staging_update", "update_failed"},
    "staging_update": {"update_ready", "update_failed"},
    "update_ready": {"applying_update", "update_failed", "update_recovered"},
    "applying_update": {"restarting_launcher", "update_failed", "update_recovered"},
    "restarting_launcher": {"reattaching_agent", "update_failed", "update_recovered"},
    "reattaching_agent": {"update_completed", "update_failed"},
    "update_failed": {"checking_update", "update_recovered"},
    "update_recovered": {"checking_update", "update_completed"},
    "update_completed": set(),
}

HELPER_EXIT_SUCCESS = 0
HELPER_EXIT_RESTART_TIMEOUT = 10
HELPER_EXIT_STAGE_MISSING = 11
HELPER_EXIT_REPLACE_FAILED = 12
HELPER_EXIT_RESTART_FAILED = 13
HELPER_EXIT_SESSION_ERROR = 14


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _same_file(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except Exception:
        return str(left) == str(right)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()


def _looks_like_windows_executable(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            mz = fh.read(64)
            if len(mz) < 64 or mz[:2] != b"MZ":
                return False
            pe_offset = int.from_bytes(mz[60:64], "little")
            fh.seek(pe_offset)
            return fh.read(4) == b"PE\x00\x00"
    except OSError:
        return False


def _normalize_version(value: str) -> tuple[int, ...]:
    numbers = re.findall(r"\d+", str(value))
    if not numbers:
        raise ValueError(f"Некорректная версия: {value!r}")
    return tuple(int(item) for item in numbers)


def _compare_versions(left: str, right: str) -> int:
    left_parts = list(_normalize_version(left))
    right_parts = list(_normalize_version(right))
    max_len = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (max_len - len(left_parts)))
    right_parts.extend([0] * (max_len - len(right_parts)))
    if left_parts < right_parts:
        return -1
    if left_parts > right_parts:
        return 1
    return 0


@dataclass(frozen=True)
class UpdateSource:
    kind: str
    value: str


@dataclass(frozen=True)
class UpdateArtifact:
    source: UpdateSource
    version: str
    sha256: str
    signature: str = ""
    publisher: str = ""


@dataclass
class UpdateSession:
    session_id: str
    state: str
    source_type: str
    source_location: str
    target_executable: str
    staged_executable: str
    backup_executable: str
    session_file: str
    helper_log_file: str
    restart_args: list[str]
    current_version: str
    target_version: str
    expected_sha256: str
    staged_sha256: str = ""
    signature: str = ""
    publisher: str = ""
    error: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        artifact: UpdateArtifact,
        current_version: str,
        target_executable: Path,
        staged_executable: Path,
        restart_args: Sequence[str],
    ) -> "UpdateSession":
        session_id = uuid.uuid4().hex
        session_file = target_executable.parent / f".launcher-update-{session_id}.json"
        helper_log_file = target_executable.parent / f".launcher-update-{session_id}.helper.log"
        backup_executable = target_executable.with_suffix(f"{target_executable.suffix}.bak")
        now = _utc_now()
        return cls(
            session_id=session_id,
            state="idle",
            source_type=artifact.source.kind,
            source_location=artifact.source.value,
            target_executable=str(target_executable.resolve(strict=False)),
            staged_executable=str(staged_executable.resolve(strict=False)),
            backup_executable=str(backup_executable.resolve(strict=False)),
            session_file=str(session_file.resolve(strict=False)),
            helper_log_file=str(helper_log_file.resolve(strict=False)),
            restart_args=list(restart_args),
            current_version=current_version,
            target_version=artifact.version,
            expected_sha256=artifact.sha256.lower(),
            signature=artifact.signature,
            publisher=artifact.publisher,
            created_at=now,
            updated_at=now,
        )

    @classmethod
    def from_file(cls, path: Path) -> "UpdateSession":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(**payload)

    def save(self) -> None:
        path = Path(self.session_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class UpdateHelperSpec:
    launcher_pid: int
    session_file: str
    helper_log_file: str
    target_executable: str
    staged_executable: str
    backup_executable: str
    restart_args: list[str]


def resolve_update_source(config: UpdateConfig) -> UpdateSource | None:
    if config.local_path.strip():
        return UpdateSource(kind="localPath", value=config.local_path.strip())

    url = config.effective_url()
    if url:
        return UpdateSource(kind="url", value=url)

    return None


def get_current_launcher_binary() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve(strict=False)

    argv0 = Path(sys.argv[0])
    if argv0.suffix.lower() == ".exe":
        return argv0.resolve(strict=False)

    return None


class SelfUpdateManager:
    def __init__(
        self,
        logger: RotatingLogger,
        http_client: object | None = None,
        process_factory=subprocess.Popen,
    ):
        self.log = logger
        self.http = http_client or requests
        self.process_factory = process_factory

    def check_update(self, config: UpdateConfig) -> UpdateArtifact:
        self._log_state("checking_update", "Проверка доступности self-update", source=config.source_location())
        source = resolve_update_source(config)
        if source is None:
            raise ValueError("Источник обновления не задан")

        artifact = UpdateArtifact(
            source=source,
            version=config.version.strip(),
            sha256=config.sha256.strip().lower(),
            signature=config.signature.strip(),
            publisher=config.publisher.strip(),
        )
        self._log_state(
            "update_available",
            "Обновление launcher найдено и готово к staging",
            source=artifact.source.value,
            version=artifact.version,
            sha256=artifact.sha256,
        )
        return artifact

    def stage_update(
        self,
        *,
        config: UpdateConfig,
        target_executable: Path,
        restart_args: Sequence[str],
        current_version: str | None = None,
    ) -> UpdateSession:
        artifact = self.check_update(config)
        target = target_executable.resolve(strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)

        existing_session = self.find_pending_session(target)
        if existing_session and existing_session.state not in {"update_failed", "update_completed", "update_recovered"}:
            raise RuntimeError(
                f"Уже существует незавершенная update-сессия {existing_session.session_id} "
                f"в состоянии {existing_session.state}"
            )

        stage_dir = target.parent / ".launcher-update-staging"
        stage_dir.mkdir(parents=True, exist_ok=True)
        staged = stage_dir / f"{target.name}.{uuid.uuid4().hex}.staged"
        session = UpdateSession.create(
            artifact=artifact,
            current_version=current_version or get_app_version(target.parent),
            target_executable=target,
            staged_executable=staged,
            restart_args=restart_args,
        )
        session.state = "staging_update"
        session.save()
        self._log_state(
            session.state,
            "Подготовка staged binary для self-update",
            session_id=session.session_id,
            target=str(target),
            staged=str(staged),
        )

        try:
            self._materialize_update_source(artifact.source, staged, target)
            self._validate_staged_artifact(
                staged_path=staged,
                target_path=target,
                artifact=artifact,
                current_version=session.current_version,
                allow_same_version=config.allow_same_version,
                allow_downgrade=config.allow_downgrade,
            )
            session.staged_sha256 = _sha256(staged)
            self.transition_session(session, "update_ready")
            self._log_state(
                session.state,
                "Staged binary успешно подготовлен",
                session_id=session.session_id,
                version=session.target_version,
                sha256=session.staged_sha256,
            )
            return session
        except Exception as exc:
            session.error = str(exc)
            self.transition_session(session, "update_failed")
            self._safe_unlink(staged)
            raise

    def apply_staged_update(
        self,
        *,
        session: UpdateSession,
        current_pid: int | None = None,
    ) -> Path:
        launcher_pid = current_pid or os.getpid()
        self.transition_session(session, "applying_update")
        helper_spec = self.build_helper_spec(launcher_pid=launcher_pid, session=session)
        command = self._build_update_command(helper_spec)
        self.process_factory(
            command,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        return Path(session.staged_executable)

    def schedule_update(
        self,
        *,
        config: UpdateConfig,
        restart_args: Sequence[str],
        current_pid: int | None = None,
        target_executable: Path | None = None,
        current_version: str | None = None,
    ) -> Path:
        target = target_executable or get_current_launcher_binary()
        if target is None:
            raise RuntimeError("Self-update доступен только для launcher .exe")

        session = self.stage_update(
            config=config,
            target_executable=target,
            restart_args=restart_args,
            current_version=current_version,
        )
        return self.apply_staged_update(session=session, current_pid=current_pid)

    def finalize_restart(
        self,
        *,
        session_path: str | None,
    ) -> UpdateSession | None:
        session = self.load_session(session_path)
        if session is None:
            return None

        self.transition_session(session, "reattaching_agent")
        self._log_state(
            session.state,
            "Launcher перезапущен после self-update и готов к reattach java-agent",
            session_id=session.session_id,
            version=session.target_version,
        )
        return session

    def complete_post_restart(
        self,
        *,
        session_path: str | None,
        attached_to_existing_agent: bool,
        agent_pid: int | None = None,
    ) -> UpdateSession | None:
        session = self.load_session(session_path)
        if session is None:
            return None

        if session.state != "update_completed":
            self.transition_session(session, "update_completed")

        outcome = "existing_agent_attached" if attached_to_existing_agent else "new_agent_started"
        self._log_state(
            session.state,
            "Self-update завершен после успешного старта launcher",
            session_id=session.session_id,
            outcome=outcome,
            agent_pid=agent_pid,
        )
        self.cleanup_session_artifacts(session, remove_session_file=True)
        return session

    def fail_post_restart(
        self,
        *,
        session_path: str | None,
        reason: str,
    ) -> UpdateSession | None:
        session = self.load_session(session_path)
        if session is None:
            return None

        session.error = reason
        if session.state != "update_failed":
            self.transition_session(session, "update_failed")
        self._log_state(
            session.state,
            "Self-update завершился ошибкой после перезапуска launcher",
            session_id=session.session_id,
            error=reason,
        )
        return session

    def recover_pending_update(
        self,
        *,
        target_executable: Path,
    ) -> UpdateSession | None:
        session = self.find_pending_session(target_executable.resolve(strict=False))
        if session is None:
            return None

        staged = Path(session.staged_executable)
        target = Path(session.target_executable)
        backup = Path(session.backup_executable)

        if session.state in {"update_completed", "update_recovered"}:
            return session

        if session.state == "update_failed":
            self._restore_backup_if_needed(session)
            self.transition_session(session, "update_recovered")
            self.cleanup_session_artifacts(session, remove_session_file=False)
            return session

        if backup.exists() and not target.exists():
            shutil.copy2(backup, target)
            self.transition_session(session, "update_recovered")
            self.cleanup_session_artifacts(session, remove_session_file=False)
            return session

        if session.state in {"update_ready", "applying_update", "restarting_launcher"} and staged.exists():
            self.transition_session(session, "update_recovered")
            self.cleanup_session_artifacts(session, remove_session_file=False)
            return session

        return session

    def transition_session(self, session: UpdateSession, new_state: str) -> None:
        previous_state = session.state
        allowed = ALLOWED_TRANSITIONS.get(previous_state, set())
        if previous_state != new_state and new_state not in allowed:
            raise ValueError(f"Недопустимый переход update-state: {previous_state} -> {new_state}")
        session.state = new_state
        session.updated_at = _utc_now()
        session.save()

    def load_session(self, session_path: str | None) -> UpdateSession | None:
        if not session_path:
            return None
        path = Path(session_path)
        if not path.is_file():
            return None
        return UpdateSession.from_file(path)

    def find_pending_session(self, target_executable: Path) -> UpdateSession | None:
        pattern = ".launcher-update-*.json"
        for candidate in sorted(target_executable.parent.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                session = UpdateSession.from_file(candidate)
            except Exception:
                continue
            if Path(session.target_executable).resolve(strict=False) == target_executable.resolve(strict=False):
                return session
        return None

    def cleanup_session_artifacts(self, session: UpdateSession, *, remove_session_file: bool) -> None:
        self._safe_unlink(Path(session.staged_executable))
        self._safe_unlink(Path(session.backup_executable))
        self._safe_unlink(Path(session.helper_log_file))
        if remove_session_file:
            self._safe_unlink(Path(session.session_file))

    def build_helper_spec(
        self,
        *,
        launcher_pid: int,
        session: UpdateSession,
    ) -> UpdateHelperSpec:
        effective_restart_args = list(session.restart_args)
        if "--updated-via-self-update" not in effective_restart_args:
            effective_restart_args.append("--updated-via-self-update")
        if "--update-session" not in effective_restart_args:
            effective_restart_args.extend(["--update-session", session.session_file])

        spec = UpdateHelperSpec(
            launcher_pid=int(launcher_pid),
            session_file=session.session_file,
            helper_log_file=session.helper_log_file,
            target_executable=session.target_executable,
            staged_executable=session.staged_executable,
            backup_executable=session.backup_executable,
            restart_args=effective_restart_args,
        )
        self._validate_helper_spec(spec)
        return spec

    def apply_helper_file_actions(self, spec: UpdateHelperSpec) -> str:
        staged = Path(spec.staged_executable)
        target = Path(spec.target_executable)
        backup = Path(spec.backup_executable)

        if not staged.exists():
            if target.exists():
                return "already_applied"
            raise FileNotFoundError("staged binary is missing")

        if target.exists():
            shutil.copy2(target, backup)
            try:
                staged.replace(target)
            except OSError:
                shutil.copy2(staged, target)
                staged.unlink(missing_ok=True)
            return "updated"

        staged.replace(target)
        return "updated"

    def rollback_helper_file_actions(self, spec: UpdateHelperSpec, *, force_restore_target: bool) -> bool:
        target = Path(spec.target_executable)
        backup = Path(spec.backup_executable)
        if not backup.exists():
            return False
        if force_restore_target or not target.exists():
            shutil.copy2(backup, target)
            return True
        return False

    def _materialize_update_source(self, source: UpdateSource, staged_path: Path, target_path: Path) -> None:
        if source.kind == "localPath":
            local_path = Path(source.value).expanduser().resolve(strict=False)
            if not local_path.is_file():
                raise FileNotFoundError(f"Файл обновления не найден: {local_path}")
            if _same_file(local_path, target_path):
                raise ValueError("Источник обновления совпадает с текущим launcher binary")
            shutil.copy2(local_path, staged_path)
            return

        response = self.http.get(source.value, timeout=30, stream=True)
        response.raise_for_status()
        with open(staged_path, "wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    fh.write(chunk)

    def _validate_staged_artifact(
        self,
        *,
        staged_path: Path,
        target_path: Path,
        artifact: UpdateArtifact,
        current_version: str,
        allow_same_version: bool,
        allow_downgrade: bool,
    ) -> None:
        if not staged_path.exists():
            raise ValueError(f"Стадированный файл обновления не создан: {staged_path}")
        if staged_path.stat().st_size <= 0:
            raise ValueError(f"Стадированный файл обновления пуст: {staged_path}")
        if not _looks_like_windows_executable(staged_path):
            raise ValueError(f"Стадированный файл не является валидным Windows executable: {staged_path}")

        actual_sha256 = _sha256(staged_path)
        if actual_sha256.lower() != artifact.sha256.lower():
            raise ValueError(
                f"SHA256 staged binary не совпадает с ожидаемым значением: "
                f"{actual_sha256} != {artifact.sha256.lower()}"
            )

        if target_path.exists() and actual_sha256.lower() == _sha256(target_path).lower():
            raise ValueError("Источник обновления идентичен текущему launcher binary")

        version_cmp = _compare_versions(artifact.version, current_version)
        if version_cmp == 0 and not allow_same_version:
            raise ValueError(
                f"Версия self-update должна быть строго выше текущей: {artifact.version} <= {current_version}"
            )
        if version_cmp < 0 and not allow_downgrade:
            raise ValueError(
                f"Downgrade launcher запрещен: {artifact.version} < {current_version}"
            )

    def _restore_backup_if_needed(self, session: UpdateSession) -> None:
        target = Path(session.target_executable)
        backup = Path(session.backup_executable)
        if backup.exists() and not target.exists():
            shutil.copy2(backup, target)

    def _build_update_command(self, spec: UpdateHelperSpec) -> list[str]:
        if os.name != "nt":
            raise RuntimeError("Self-update helper пока реализован только для Windows")

        restart_args_literal = ", ".join(_ps_quote(arg) for arg in spec.restart_args)
        script = f"""
$ErrorActionPreference = 'Stop'
$launcherPid = {int(spec.launcher_pid)}
$sessionPath = {_ps_quote(spec.session_file)}
$helperLog = {_ps_quote(spec.helper_log_file)}
$args = @({restart_args_literal})

function Write-HelperLog([string]$Message) {{
    Add-Content -LiteralPath $helperLog -Value $Message -Encoding UTF8
}}

function Set-SessionState([string]$State, [string]$Error = '') {{
    $data = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $data.state = $State
    $data.error = $Error
    $data.updated_at = [DateTime]::UtcNow.ToString('o')
    $data | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $sessionPath -Encoding UTF8
}}

for ($i = 0; $i -lt 240; $i++) {{
    if (-not (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue)) {{
        break
    }}
    Start-Sleep -Milliseconds 500
}}
if (Get-Process -Id $launcherPid -ErrorAction SilentlyContinue) {{
    Write-HelperLog 'launcher process did not exit in time'
    exit {HELPER_EXIT_RESTART_TIMEOUT}
}}

$session = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 | ConvertFrom-Json
$target = [string]$session.target_executable
$staged = [string]$session.staged_executable
$backup = [string]$session.backup_executable

if (-not (Test-Path -LiteralPath $staged) -and -not (Test-Path -LiteralPath $target)) {{
    Write-HelperLog 'neither staged nor target binary exists'
    Set-SessionState 'update_failed' 'staged binary is missing'
    exit {HELPER_EXIT_STAGE_MISSING}
}}

if (-not (Test-Path -LiteralPath $staged) -and (Test-Path -LiteralPath $target)) {{
    Write-HelperLog 'helper rerun detected: staged binary already applied, continuing with restart'
    Set-SessionState 'restarting_launcher'
}}

if (Test-Path -LiteralPath $staged) {{
    Set-SessionState 'applying_update'

    try {{
        if (Test-Path -LiteralPath $target) {{
            Copy-Item -LiteralPath $target -Destination $backup -Force
            try {{
                Move-Item -LiteralPath $staged -Destination $target -Force
            }} catch {{
                Copy-Item -LiteralPath $staged -Destination $target -Force
                Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
            }}
        }} else {{
            Move-Item -LiteralPath $staged -Destination $target -Force
        }}
    }} catch {{
        Write-HelperLog ('replace failed: ' + $_.Exception.Message)
        if ((Test-Path -LiteralPath $backup) -and -not (Test-Path -LiteralPath $target)) {{
            Copy-Item -LiteralPath $backup -Destination $target -Force
        }}
        Set-SessionState 'update_failed' $_.Exception.Message
        exit {HELPER_EXIT_REPLACE_FAILED}
    }}
}}

Set-SessionState 'restarting_launcher'

try {{
    Start-Process -FilePath $target -ArgumentList $args | Out-Null
    exit {HELPER_EXIT_SUCCESS}
}} catch {{
    Write-HelperLog ('restart failed: ' + $_.Exception.Message)
    if ((Test-Path -LiteralPath $backup) -and (Test-Path -LiteralPath $target)) {{
        Copy-Item -LiteralPath $backup -Destination $target -Force
    }}
    Set-SessionState 'update_failed' $_.Exception.Message
    exit {HELPER_EXIT_RESTART_FAILED}
}}
"""
        return ["powershell", "-NoProfile", "-Command", script]

    def _validate_helper_spec(self, spec: UpdateHelperSpec) -> None:
        required_paths = {
            "session_file": spec.session_file,
            "helper_log_file": spec.helper_log_file,
            "target_executable": spec.target_executable,
            "staged_executable": spec.staged_executable,
            "backup_executable": spec.backup_executable,
        }
        for name, value in required_paths.items():
            if not str(value).strip():
                raise ValueError(f"Helper contract требует непустой путь: {name}")

        if spec.launcher_pid <= 0:
            raise ValueError("Helper contract требует корректный launcher_pid")

        distinct_paths = {Path(value).resolve(strict=False) for value in required_paths.values()}
        if len(distinct_paths) != len(required_paths):
            raise ValueError("Helper contract требует уникальные пути target/staged/backup/session/log")

    def _safe_unlink(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _log_state(self, state: str, message: str, **details: Any) -> None:
        extra = " ".join(f"{key}={value}" for key, value in details.items() if value not in ("", None))
        final_message = f"[{state}] {message}"
        if extra:
            final_message = f"{final_message} | {extra}"
        self.log.log(final_message, comp="Update")
