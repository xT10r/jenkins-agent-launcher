"""
Точка входа: CLI-парсинг, выбор режима (GUI / console / test-config).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def _parse_args():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--test-config", action="store_true")
    parser.add_argument("--no-gui", action="store_true")
    parser.add_argument("--updated-via-self-update", action="store_true")
    parser.add_argument("--update-session")
    parser.add_argument("--url"); parser.add_argument("--name"); parser.add_argument("--secret")
    parser.add_argument("--tunnel"); parser.add_argument("--websocket", action="store_true")
    parser.add_argument("--direct"); parser.add_argument("--instance-identity")
    parser.add_argument("--protocols"); parser.add_argument("--java-opts"); parser.add_argument("--java-home")
    parser.add_argument("--fallback-url"); parser.add_argument("--work-dir")
    parser.add_argument("--jar-path"); parser.add_argument("--log-path")
    parser.add_argument("--max-restarts", type=int, default=None)
    parser.add_argument("--restart-delay", type=int, default=None)
    parser.add_argument("--auto-update", action="store_true", default=None)
    parser.add_argument("--no-auto-update", action="store_true")
    parser.add_argument("--timeout", type=int, default=None)
    return parser.parse_args()


def _cli_to_dict(args):
    """Преобразовать argparse.Namespace в dict для resolve_config."""
    raw = {k: v for k, v in vars(args).items() if v is not None and v is not False}
    raw.pop("updated_via_self_update", None)
    raw.pop("update_session", None)
    key_map = {
        "url": "jenkins_url",
        "name": "agent_name",
        "fallback_url": "fallback_jar_url",
        "jar_path": "agent_jar_path",
        "timeout": "jenkins_timeout",
    }

    normalized: dict[str, object] = {}
    for key, value in raw.items():
        normalized[key_map.get(key, key)] = value
    return normalized


def _resolve_icon_path(
    project_dir: Path,
    *,
    frozen: bool | None = None,
    bundle_dir: Path | None = None,
) -> str:
    candidates = []
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if frozen:
        if bundle_dir is None:
            bundle_dir = Path(getattr(sys, "_MEIPASS", project_dir))
        candidates.append(bundle_dir / "assets" / "jenkins.ico")
    candidates.append(project_dir / "assets" / "jenkins.ico")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return ""


def main():
    from .config import resolve_config, get_project_dir, save_ui_theme
    from .instance_guard import ConfigInstanceGuard
    from .logger import RotatingLogger
    from .self_update import SelfUpdateManager, get_current_launcher_binary
    from .version import get_app_version
    from .gui.dialogs import show_help as gui_show_help

    args = _parse_args()
    project_dir = get_project_dir()
    cli_dict = _cli_to_dict(args)
    app_version = get_app_version(project_dir)

    # ── Test-config ──
    if args.test_config:
        cfg, errors = resolve_config(project_dir, cli_dict)
        if errors:
            for e in errors:
                print(f"  [ERR] {e}", file=sys.stderr)
            sys.exit(1)
        print(f"Конфигурация валидна: {cfg.agent.jenkins_url}")
        sys.exit(0)

    # ── Resolve config ──
    cfg, errors = resolve_config(project_dir, cli_dict)

    # ── Logger ──
    from .logger import LogConfig
    logger = RotatingLogger(
        project_dir=project_dir,
        config=LogConfig(
            dir=cfg.logging.dir,
            rotation=cfg.logging.rotation,
            max_days=cfg.logging.max_days,
            max_size_mb=cfg.logging.max_size_mb,
            path=cfg.agent.log_path,
        ),
    )

    # Очистка старых логов
    try:
        logger.cleanup_old()
    except Exception:
        pass

    logger.log(f"Приложение запущено (v{app_version})", comp="Launcher")
    logger.log(
        f"PID launcher: {os.getpid()}. Отдельный java-процесс Jenkins-агента будет запущен и управляться этим launcher.",
        comp="Launcher",
    )
    for note in cfg.diagnostics:
        logger.log(note, comp="Config")

    if errors:
        for e in errors:
            logger.log(e, level="ERROR", comp="Config")
        logger.log("Конфигурация не заполнена", level="WARN", comp="Config")
        logger.log("Приложение ожидает: отредактируйте config.json или передайте параметры CLI", level="WARN", comp="Config")

    logger.log(f"Логи: {logger.get_current_path()} (rotation={cfg.logging.rotation}, maxDays={cfg.logging.max_days})")
    logger.log(f"Подключение: {cfg.agent.jenkins_url or 'НЕ ЗАДАН'} | Агент: {cfg.agent.agent_name or 'НЕ ЗАДАН'}", comp="Config")
    if cfg.agent.tunnel:
        logger.log(f"Туннель: {cfg.agent.tunnel}", comp="Config")
    updater = SelfUpdateManager(logger=logger)
    current_binary = get_current_launcher_binary()
    if current_binary is not None:
        try:
            recovered_session = updater.recover_pending_update(target_executable=current_binary)
            if recovered_session and recovered_session.state == "update_recovered":
                logger.log(
                    f"Обнаружена и безопасно восстановлена незавершенная update-сессия {recovered_session.session_id}.",
                    level="WARN",
                    comp="Update",
                )
        except Exception as exc:
            logger.log(f"Recovery незавершенного self-update не выполнен: {exc}", level="ERROR", comp="Update")

    instance_guard = None
    if not errors:
        instance_guard = ConfigInstanceGuard(cfg)
        acquired, conflict_message = instance_guard.acquire()
        if not acquired:
            logger.log(conflict_message or "Экземпляр с теми же настройками уже запущен", level="ERROR", comp="Launcher")
            logger.close()
            sys.exit(1)

    if args.updated_via_self_update:
        finalized_session = updater.finalize_restart(session_path=args.update_session)
        if finalized_session is None:
            logger.log(
                "Launcher перезапущен после self-update; session metadata не найдена, повторная проверка обновления пропущена.",
                level="WARN",
                comp="Update",
            )
        else:
            logger.log(
                f"Launcher перезапущен после self-update; update-сессия {finalized_session.session_id} "
                "переведена в режим обязательного reattach существующего java-agent.",
                comp="Update",
            )
    elif not errors and cfg.update.enabled:
        if current_binary is None:
            logger.log(
                "Self-update пропущен: launcher запущен не из .exe, безопасная замена бинаря недоступна.",
                level="WARN",
                comp="Update",
            )
        else:
            try:
                staged_path = updater.schedule_update(
                    config=cfg.update,
                    restart_args=sys.argv[1:],
                    target_executable=current_binary,
                    current_version=app_version,
                )
                logger.log(
                    f"Self-update запланирован. Новый бинарь подготовлен: {staged_path}",
                    comp="Update",
                )
                if instance_guard:
                    instance_guard.release()
                logger.close()
                sys.exit(0)
            except Exception as exc:
                logger.log(f"Self-update не выполнен: {exc}", level="ERROR", comp="Update")

    active_ignored_vars = [
        item for item in cfg.environment.ignored_vars
        if os.environ.get(item.name)
    ]
    for item in active_ignored_vars:
        reason = f" Причина: {item.reason}" if item.reason else ""
        logger.log(
            f"Переменная окружения будет скрыта от java-процесса: {item.name}.{reason}",
            comp="Security",
        )

    # ── GUI mode ──
    if not args.no_gui:
        from .agent_controller import AgentController
        from .gui.main_window import MainWindow

        icon_path = _resolve_icon_path(project_dir)

        # Функции для кнопок (работают и при ctrl=None)
        def do_start():
            if ctrl is None:
                logger.log("Невозможно запустить: конфигурация не заполнена", level="WARN", comp="UI")
            elif ctrl.is_running:
                logger.log("Агент уже запущен", comp="UI")
            else:
                logger.log("Запуск агента (пользователь)", comp="UI")
                ctrl.start()

        def do_restart():
            if ctrl is None:
                logger.log("Невозможно перезапустить: конфигурация не заполнена", level="WARN", comp="UI")
            else:
                logger.log("Перезапуск агента (пользователь)", comp="UI")
                ctrl.restart()

        def do_stop():
            if ctrl is None:
                logger.log("Невозможно остановить: агент не запущен", level="WARN", comp="UI")
            else:
                logger.log("Остановка агента (пользователь)", comp="UI")
                ctrl.stop()

        win = MainWindow(
            app_name="Jenkins JNLP Agent Launcher",
            app_version=app_version,
            company="Jenkins Agent Launcher Contributors",
            agent_name=cfg.agent.agent_name,
            icon_path=icon_path,
            log_path=logger.get_current_path(),
            launcher_pid=os.getpid(),
            parent_pid=os.getppid(),
            on_start=do_start,
            on_restart=do_restart,
            on_stop=do_stop,
            on_exit=lambda: (
                logger.log("Приложение остановлено пользователем", comp="Launcher"),
                instance_guard.release() if instance_guard else None,
                logger.close(),
                win.hide(),
                sys.exit(0),
            ),
            on_show_log=lambda: subprocess.Popen(["notepad.exe", logger.get_current_path()]),
            on_theme_change=lambda theme: (
                save_ui_theme(project_dir, theme),
                logger.log(f"Тема интерфейса изменена: {theme}", comp="UI"),
            ),
            dark_theme=(cfg.ui.theme == "dark"),
            start_minimized=cfg.ui.start_minimized,
        )

        # GUI callback → logger
        logger.set_gui_callback(win.append_log)

        # Controller → GUI status + notifications (только если конфиг валиден)
        if errors:
            if args.updated_via_self_update:
                updater.fail_post_restart(
                    session_path=args.update_session,
                    reason="Конфигурация launcher невалидна после self-update",
                )
            # Пустой контроллер для GUI без агента
            ctrl = None
            win.set_status("Конфигурация не заполнена", 0)
        else:
            # Уведомления
            def notify_on_status(text, pid):
                win.set_status(text, pid)
                if "Работает" in text:
                    win.notify("Агент запущен", f"PID: {pid}")
                elif "Остановлен" in text:
                    win.notify("Агент остановлен", "Успешно")
                elif "Ошибка" in text or "лимит" in text.lower():
                    win.notify_warning("Ошибка", text)

            ctrl = AgentController(
                config=cfg,
                logger=logger,
                on_status=notify_on_status,
                on_progress=lambda dl, total: win.set_status(
                    f"Загрузка: {dl // 1024}KB / {total // 1024}KB", 0
                ) if total > 0 else None,
                updated_via_self_update=args.updated_via_self_update,
                post_update_session_path=args.update_session,
                update_manager=updater,
            )

            # Start controller
            ctrl.start()

        # Run GUI event loop
        rc = win.exec_()
        logger.log("Приложение остановлено", comp="Launcher")
        if instance_guard:
            instance_guard.release()
        logger.close()
        sys.exit(rc)

    # ── Console mode ──
    else:
        if errors:
            if args.updated_via_self_update:
                updater.fail_post_restart(
                    session_path=args.update_session,
                    reason="Конфигурация launcher невалидна после self-update",
                )
            for e in errors:
                print(f"  [ERR] {e}", file=sys.stderr)
            logger.log("Консольный режим остановлен: конфигурация невалидна", level="ERROR", comp="Config")
            logger.close()
            sys.exit(1)

        print(f"Agent PID: запускается...  (Ctrl+C to stop)")
        try:
            from .agent_controller import AgentController
            import time

            ctrl = AgentController(
                config=cfg,
                logger=logger,
                on_status=lambda text, pid: print(f"  [{text}]"),
                updated_via_self_update=args.updated_via_self_update,
                post_update_session_path=args.update_session,
                update_manager=updater,
            )
            ctrl.start()

            while ctrl.is_running:
                time.sleep(1)

            logger.log("Приложение остановлено", comp="Launcher")
            if instance_guard:
                instance_guard.release()
            logger.close()
            sys.exit(0)

        except KeyboardInterrupt:
            logger.log("Прервано (Ctrl+C)")
            if instance_guard:
                instance_guard.release()
            logger.close()
            sys.exit(0)
        except Exception as e:
            logger.log(f"Критическая ошибка: {e}", level="ERROR")
            if instance_guard:
                instance_guard.release()
            logger.close()
            sys.exit(1)


if __name__ == "__main__":
    main()
