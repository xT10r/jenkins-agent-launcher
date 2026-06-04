# Changelog

Все значимые изменения проекта документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/0.3.0/), проект использует [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Добавлен `CHANGELOG.md` для ведения release notes в формате Keep a Changelog.
- Добавлена документация по эксплуатации и релизам в `docs/operations.md`.
- Добавлена документация по ведению changelog и release-заголовкам в `docs/release-process.md`.
- Добавлено получение Jenkins secret из JNLP-файла агента с опциональной записью в runtime config.
- Добавлена настройка временного каталога Java/launcher через `agent.tempDir`, `--temp-dir` и `JENKINS_TEMP_DIR`.

### Changed

- Переработан корневой `README.md`: оставлен короткий входной документ, подробности вынесены в `docs/`.
- Уточнено нейтральное имя publisher metadata: `Jenkins Agent Launcher Contributors`.

## [0.0.1] - 2026-06-01

### Added

- Реализован Windows launcher для Jenkins inbound agent с GUI, tray-иконкой и console mode.
- Добавлен запуск `agent.jar` под управлением launcher с мониторингом процесса и политикой рестартов.
- Добавлена загрузка `agent.jar` с retry-политикой, timeout-настройками и progress callback.
- Добавлен fallback URL для скачивания `agent.jar`.
- Добавлена конфигурация через `config/config.json`, legacy `config.json`, CLI-аргументы и переменные окружения `JENKINS_*`.
- Добавлена валидация runtime-конфигурации и режим `--test-config`.
- Добавлена фильтрация выбранных `JENKINS_*` переменных перед запуском Java-процесса.
- Добавлена передача Jenkins secret через временный `@file` вместо прямой передачи в командной строке.
- Добавлено затирание временного файла секрета перед удалением.
- Добавлено логирование с ротацией и выводом статусов запуска, скачивания, Java-процесса и ошибок подготовки.
- Добавлена поддержка явного выбора Java через `agent.javaHome` / `--java-home`.
- Добавлен self-update flow с проверкой SHA-256, publisher metadata и recovery незавершённых update-сессий.
- Добавлена сборка standalone `.exe` через PyInstaller.
- Добавлена генерация Windows version resource и runtime build metadata из `config/build.json` / `config/build.template.json`.
- Добавлена иконка приложения и propagation иконки в `QApplication`, главное окно, taskbar/Alt-Tab и packaged `.exe`.
- Добавлен test runner `scripts/run-tests.ps1` / `scripts/run-tests.bat` для стабильного запуска тестов на Windows.

### Changed

- Runtime-конфиги `config/config.json` и `config/build.json` вынесены в local-only ignored files; tracked templates остаются источником примеров.
- PyInstaller запускается через Python helper со структурированными аргументами вместо склейки командной строки в batch-файле.
- Build version зафиксирована как SemVer `0.0.1`; Windows file version генерируется как `0.0.1.0`.

### Fixed

- Улучшена обработка tray startup и статуса Jenkins connection в GUI.
- Улучшены размеры окна и about dialog.
- Исправлено встраивание build metadata в packaged launcher.
- Исправлена обработка build metadata для путей, пробелов, кавычек и отсутствующей иконки.
- Восстановлено отображение иконки приложения в GUI/taskbar/Alt-Tab и packaged binary.

### Security

- Уменьшен риск утечки Jenkins secret через command line за счёт передачи секрета через временный файл.
- Добавлена изоляция окружения Java-процесса от выбранных `JENKINS_*` переменных.
- Добавлены проверки placeholder-секретов и обязательных runtime-полей.

[unreleased]: https://github.com/xT10r/jenkins-agent-launcher/compare/v0.0.1...HEAD
[0.0.1]: https://github.com/xT10r/jenkins-agent-launcher/releases/tag/v0.0.1
