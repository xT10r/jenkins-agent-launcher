"""Тесты production-ready self-update lifecycle."""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config import UpdateConfig
from src.logger import RotatingLogger
from src.self_update import (
    SelfUpdateManager,
    resolve_update_source,
)


def _fake_pe_bytes(payload: bytes = b"binary") -> bytes:
    content = bytearray(256)
    content[0:2] = b"MZ"
    content[60:64] = (128).to_bytes(4, "little")
    content[128:132] = b"PE\x00\x00"
    content[132:132 + len(payload)] = payload
    return bytes(content)


def _write_fake_exe(path: Path, payload: bytes = b"binary") -> str:
    data = _fake_pe_bytes(payload)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_resolve_update_source_prefers_local_path():
    cfg = UpdateConfig(
        enabled=True,
        url="https://downloads.example.com/launcher.exe",
        local_path="C:/artifacts/launcher.exe",
        version="1.1.0.0",
        sha256="a" * 64,
    )

    source = resolve_update_source(cfg)

    assert source is not None
    assert source.kind == "localPath"
    assert source.value == "C:/artifacts/launcher.exe"


def test_stage_update_from_local_path_creates_update_ready_session(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source_file = tmp_path / "source.exe"
    target_file = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source_file, b"updated-binary")
    _write_fake_exe(target_file, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source_file),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target_file,
        restart_args=["--no-gui"],
        current_version="1.0.0.0",
    )

    staged = Path(session.staged_executable)
    assert session.state == "update_ready"
    assert staged.exists()
    assert staged.read_bytes() == source_file.read_bytes()
    assert Path(session.session_file).exists()


def test_stage_update_rejects_double_update_while_pending_session_exists(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source_a = tmp_path / "source-a.exe"
    source_b = tmp_path / "source-b.exe"
    target = tmp_path / "target.exe"
    sha256_a = _write_fake_exe(source_a, b"updated-a")
    sha256_b = _write_fake_exe(source_b, b"updated-b")
    _write_fake_exe(target, b"current-binary")

    first_session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source_a),
            version="1.1.0.0",
            sha256=sha256_a,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )

    with pytest.raises(RuntimeError, match="незавершенная update-сессия"):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source_b),
                version="1.2.0.0",
                sha256=sha256_b,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )

    assert first_session.state == "update_ready"
    assert Path(first_session.staged_executable).exists()


def test_stage_update_from_url_creates_update_ready_session(tmp_path):
    logger = RotatingLogger(tmp_path)
    payload = _fake_pe_bytes(b"updated-from-url")
    sha256 = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "target.exe"
    _write_fake_exe(target, b"current-binary")

    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.iter_content.return_value = [payload[:128], payload[128:]]
    http_client = MagicMock()
    http_client.get.return_value = response

    manager = SelfUpdateManager(logger=logger, http_client=http_client)
    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            url="https://downloads.example.com/launcher.exe",
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )

    assert session.state == "update_ready"
    assert Path(session.staged_executable).read_bytes() == payload
    http_client.get.assert_called_once()


def test_stage_update_rejects_same_file(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    binary = tmp_path / "launcher.exe"
    sha256 = _write_fake_exe(binary, b"current-binary")

    with pytest.raises(ValueError):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(binary),
                version="1.1.0.0",
                sha256=sha256,
            ),
            target_executable=binary,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_identical_binary_content(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"same-binary")
    _write_fake_exe(target, b"same-binary")

    with pytest.raises(ValueError):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source),
                version="1.1.0.0",
                sha256=sha256,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_invalid_sha256(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    with pytest.raises(ValueError):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source),
                version="1.1.0.0",
                sha256="f" * 64,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_broken_local_artifact(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "broken.exe"
    target = tmp_path / "target.exe"
    source.write_bytes(b"not-an-exe")
    _write_fake_exe(target, b"current-binary")
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

    with pytest.raises(ValueError, match="Windows executable"):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source),
                version="1.1.0.0",
                sha256=sha256,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_unreachable_url(tmp_path):
    logger = RotatingLogger(tmp_path)
    http_client = MagicMock()
    http_client.get.side_effect = RuntimeError("network unreachable")
    manager = SelfUpdateManager(logger=logger, http_client=http_client)
    target = tmp_path / "target.exe"
    _write_fake_exe(target, b"current-binary")

    with pytest.raises(RuntimeError, match="network unreachable"):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                url="https://downloads.example.com/launcher.exe",
                version="1.1.0.0",
                sha256="a" * 64,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_same_version_by_default(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    with pytest.raises(ValueError):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source),
                version="1.0.0.0",
                sha256=sha256,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_rejects_downgrade_by_default(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    with pytest.raises(ValueError):
        manager.stage_update(
            config=UpdateConfig(
                enabled=True,
                local_path=str(source),
                version="0.9.0.0",
                sha256=sha256,
            ),
            target_executable=target,
            restart_args=[],
            current_version="1.0.0.0",
        )


def test_stage_update_accepts_same_version_with_service_flag(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.0.0.0",
            sha256=sha256,
            allow_same_version=True,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )

    assert session.state == "update_ready"


def test_schedule_update_spawns_helper_with_session_marker(tmp_path):
    logger = RotatingLogger(tmp_path)
    commands = []

    def fake_process(command, **kwargs):
        commands.append(command)
        return object()

    manager = SelfUpdateManager(logger=logger, process_factory=fake_process)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    staged = manager.schedule_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        restart_args=["--no-gui"],
        target_executable=target,
        current_version="1.0.0.0",
    )

    assert Path(staged).exists()
    assert commands
    assert commands[0][:3] == ["powershell", "-NoProfile", "-Command"]
    assert "--updated-via-self-update" in commands[0][3]
    assert "--update-session" in commands[0][3]


def test_apply_helper_file_actions_is_idempotent_on_rerun(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    current_bytes = _fake_pe_bytes(b"current-binary")
    target.write_bytes(current_bytes)

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=["--no-gui"],
        current_version="1.0.0.0",
    )
    spec = manager.build_helper_spec(launcher_pid=1234, session=session)

    first_outcome = manager.apply_helper_file_actions(spec)
    second_outcome = manager.apply_helper_file_actions(spec)

    assert first_outcome == "updated"
    assert second_outcome == "already_applied"
    assert target.read_bytes() == source.read_bytes()
    assert Path(spec.backup_executable).read_bytes() == current_bytes
    assert not Path(spec.staged_executable).exists()


def test_apply_helper_file_actions_keeps_staged_binary_on_failed_backup(tmp_path, monkeypatch):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    original_target_bytes = _fake_pe_bytes(b"current-binary")
    target.write_bytes(original_target_bytes)

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    spec = manager.build_helper_spec(launcher_pid=1234, session=session)

    original_copy2 = __import__("shutil").copy2

    def failing_copy2(src, dst, *args, **kwargs):
        if Path(dst) == Path(spec.backup_executable):
            raise PermissionError("backup is locked")
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr("src.self_update.shutil.copy2", failing_copy2)

    with pytest.raises(PermissionError):
        manager.apply_helper_file_actions(spec)

    assert Path(spec.staged_executable).exists()
    assert Path(spec.staged_executable).read_bytes() == source.read_bytes()
    assert target.read_bytes() == original_target_bytes
    assert not Path(spec.backup_executable).exists()


def test_rollback_helper_file_actions_restores_backup_after_restart_failure(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    original_target_bytes = _fake_pe_bytes(b"current-binary")
    target.write_bytes(original_target_bytes)

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    spec = manager.build_helper_spec(launcher_pid=1234, session=session)
    manager.apply_helper_file_actions(spec)
    target.write_bytes(_fake_pe_bytes(b"broken-after-restart"))

    restored = manager.rollback_helper_file_actions(spec, force_restore_target=True)

    assert restored is True
    assert target.read_bytes() == original_target_bytes
    assert Path(spec.backup_executable).exists()


def test_finalize_restart_completes_and_cleans_session(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    Path(session.backup_executable).write_bytes(b"backup")
    manager.transition_session(session, "applying_update")
    manager.transition_session(session, "restarting_launcher")

    finalized = manager.finalize_restart(session_path=session.session_file)

    assert finalized is not None
    assert finalized.state == "reattaching_agent"
    assert Path(session.session_file).exists()
    assert Path(session.backup_executable).exists()
    assert Path(session.staged_executable).exists()


def test_complete_post_restart_completes_and_cleans_session(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    Path(session.backup_executable).write_bytes(b"backup")
    manager.transition_session(session, "applying_update")
    manager.transition_session(session, "restarting_launcher")
    manager.finalize_restart(session_path=session.session_file)

    completed = manager.complete_post_restart(
        session_path=session.session_file,
        attached_to_existing_agent=True,
        agent_pid=4321,
    )

    assert completed is not None
    assert completed.state == "update_completed"
    assert not Path(session.session_file).exists()
    assert not Path(session.backup_executable).exists()
    assert not Path(session.staged_executable).exists()


def test_recover_pending_update_marks_session_recovered(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    recovered = manager.recover_pending_update(target_executable=target)

    assert recovered is not None
    assert recovered.state == "update_recovered"
    assert Path(recovered.session_file).exists()
    payload = json.loads(Path(recovered.session_file).read_text(encoding="utf-8"))
    assert payload["state"] == "update_recovered"


def test_recover_pending_update_restores_backup_after_partially_applied_update(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    original_target_bytes = _fake_pe_bytes(b"current-binary")
    target.write_bytes(original_target_bytes)

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    manager.transition_session(session, "applying_update")
    Path(session.backup_executable).write_bytes(original_target_bytes)
    target.unlink()

    recovered = manager.recover_pending_update(target_executable=target)

    assert recovered is not None
    assert recovered.state == "update_recovered"
    assert target.read_bytes() == original_target_bytes
    assert not Path(session.backup_executable).exists()
    assert not Path(session.staged_executable).exists()


def test_finalize_restart_is_idempotent_for_repeated_restart_with_same_session(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    manager.transition_session(session, "applying_update")
    manager.transition_session(session, "restarting_launcher")

    first_finalize = manager.finalize_restart(session_path=session.session_file)
    second_finalize = manager.finalize_restart(session_path=session.session_file)

    assert first_finalize is not None
    assert second_finalize is not None
    assert first_finalize.state == "reattaching_agent"
    assert second_finalize.state == "reattaching_agent"
    payload = json.loads(Path(session.session_file).read_text(encoding="utf-8"))
    assert payload["state"] == "reattaching_agent"


def test_fail_post_restart_marks_session_failed_and_keeps_metadata(tmp_path):
    logger = RotatingLogger(tmp_path)
    manager = SelfUpdateManager(logger=logger)
    source = tmp_path / "source.exe"
    target = tmp_path / "target.exe"
    sha256 = _write_fake_exe(source, b"updated-binary")
    _write_fake_exe(target, b"current-binary")

    session = manager.stage_update(
        config=UpdateConfig(
            enabled=True,
            local_path=str(source),
            version="1.1.0.0",
            sha256=sha256,
        ),
        target_executable=target,
        restart_args=[],
        current_version="1.0.0.0",
    )
    manager.transition_session(session, "applying_update")
    manager.transition_session(session, "restarting_launcher")
    manager.finalize_restart(session_path=session.session_file)

    failed = manager.fail_post_restart(
        session_path=session.session_file,
        reason="ambiguous attach candidates",
    )

    assert failed is not None
    assert failed.state == "update_failed"
    assert failed.error == "ambiguous attach candidates"
    assert Path(session.session_file).exists()
