# Jenkins Agent Launcher

![release](https://img.shields.io/badge/release-v0.0.1-blue)
![platform](https://img.shields.io/badge/platform-Windows%2010%2F11%20%2B%20Server-informational)
![python](https://img.shields.io/badge/python-3.12%2B-informational)
![packaging](https://img.shields.io/badge/packaging-PyInstaller-informational)

Windows launcher для Jenkins inbound agent. Приложение помогает запускать `agent.jar` предсказуемо: скачать его с Jenkins или fallback-источника, записать ошибки ещё до старта Java-процесса, показать статус пользователю, перезапустить агент при падении и оставить понятный лог для диагностики.

## Что решает

Обычный запуск Jenkins inbound agent часто разваливается в самых неудобных местах: `agent.jar` не скачался, Java не найдена, SSL-сертификат не проходит проверку, секрет оказался в командной строке, агент упал без понятного лога, а пользователь видит только исчезнувшее окно.

Этот launcher закрывает эти сценарии:

- проверяет конфигурацию до запуска агента;
- скачивает `agent.jar` с retry-политикой;
- поддерживает fallback URL для `agent.jar`;
- может получать Jenkins secret из JNLP-файла агента;
- пишет лог ошибок подготовки, скачивания, проверки Java и работы агента;
- запускает Java-процесс с изоляцией выбранных `JENKINS_*` переменных;
- передаёт Jenkins secret через временный `@file`, а не напрямую в командной строке;
- следит за процессом агента и перезапускает его по заданной политике;
- показывает GUI/tray-интерфейс для запуска, остановки, рестарта и просмотра логов;
- собирается в standalone `.exe` с version metadata.

## Быстрый старт

Создать окружение:

```cmd
scripts\setup.bat
```

Создать runtime-конфиг из шаблона:

```cmd
copy config\config.template.json config\config.json
notepad config\config.json
```

Минимальный конфиг:

```json
{
  "agent": {
    "jenkinsUrl": "https://jenkins.example.com",
    "agentName": "windows-agent-1",
    "secret": ""
  }
}
```

Проверить конфигурацию без запуска агента:

```cmd
venv\Scripts\python.exe run.py --test-config
```

Запустить из исходников:

```cmd
scripts\run-dev.bat
```

Собрать `.exe`:

```cmd
scripts\build.bat
```

Результат сборки: `agent-launcher.exe` в корне репозитория.

## Конфигурация

Порядок источников:

1. значения по умолчанию;
2. `config\config.json`;
3. legacy-файл `config.json` в корне;
4. аргументы командной строки;
5. переменные окружения `JENKINS_*`.

Если `config\config.json` отсутствует, приложение может создать его из `config\config.template.json`.

Поддерживаемые секции:

| Секция | Назначение |
|--------|------------|
| `agent` | Jenkins URL, имя агента, secret, tunnel, Java, work dir, log file |
| `logging` | директория логов, ротация, срок хранения, лимит размера |
| `download` | timeout, retry count, задержка retry, размер чанка |
| `jnlp` | получение secret из JNLP и опциональная запись в config |
| `fallback` | резервный URL для `agent.jar` и TLS policy |
| `behavior` | рестарты, задержка рестарта, обновление `agent.jar` |
| `environment` | переменные, удаляемые перед запуском Java |
| `ui` | тема и старт в свёрнутом виде |

## GUI и console mode

| Режим | Команда | Поведение |
|-------|---------|-----------|
| GUI | `run.py` или packaged `.exe` | окно, tray, управление агентом, live-log |
| Console | `run.py --no-gui` | без GUI, статусы в консоль, лог в файл |
| Проверка конфига | `run.py --test-config` | валидация и выход |

Примеры:

```cmd
agent-launcher.exe --url https://jenkins.example.com --name windows-agent-1 --secret <secret>
agent-launcher.exe --url https://jenkins.example.com --name windows-agent-1 --jnlp
agent-launcher.exe --no-gui --temp-dir <temp-dir>
agent-launcher.exe --no-gui --java-home <java-home> --work-dir <work-dir>
agent-launcher.exe --test-config
```

## Безопасность

Реализовано:

- Jenkins secret передаётся Java через временный `@file`;
- запись secret из JNLP в `config.json` выполняется только при `jnlp.saveSecret=true` или `--jnlp-save-secret`;
- временный файл секрета затирается перед удалением;
- выбранные `JENKINS_*` переменные удаляются из окружения Java-процесса;
- placeholder-значения в конфиге отклоняются валидацией;
- TLS-поведение задаётся через `agent.verifySsl` и `fallback.verifySsl`;
- self-update metadata содержит ожидаемый publisher и SHA-256.

Операционные требования:

- не хранить реальные secrets в репозитории;
- защитить `config\config.json` ACL-правами;
- использовать HTTPS Jenkins URL с валидным сертификатом;
- обновлять Java на целевых машинах;
- подписывать release-бинарь перед широким распространением.

## Тесты

Для этого репозитория используйте test runner, а не прямой `pytest`:

```cmd
scripts\run-tests.bat
```

Точечный запуск:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\run-tests.ps1 tests/test_build_metadata.py -v
```

Runner создаёт отдельный временный каталог и обходит известные Windows ACL/temp cleanup проблемы.

## Структура репозитория

```text
assets/                     иконка приложения
config/                     шаблоны runtime/build конфигурации
docs/                       актуальная документация
scripts/                    setup, test, build и packaging helpers
src/                        исходный код приложения
src/gui/                    PyQt5 окно, dialogs, tray integration
tests/                      unit и integration tests
run.py                      entry point для запуска из исходников
```

## Документация

| Документ | Назначение |
|----------|------------|
| [docs/README.md](docs/README.md) | навигация по документации |
| [docs/operations.md](docs/operations.md) | эксплуатация, fallback, логирование, build metadata и signing notes |
| [docs/specification.md](docs/specification.md) | текущее поведение и ограничения |

Если документация расходится с кодом, считать код и тесты главным источником правды.
