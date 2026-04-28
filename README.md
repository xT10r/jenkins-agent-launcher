# Jenkins JNLP Agent Launcher

**Версия:** 2.0
**Язык:** Python 3.12+
**Платформа:** Windows 10/11

Запуск Jenkins JNLP агента в пользовательской сессии с:
- иконкой в трее с контекстным меню и уведомлениями;
- тёмной темой GUI (переключение по Ctrl+T);
- автоматическим рестартом при падении (настраиваемый лимит);
- структурированным логированием с ротацией (daily/weekly/size);
- retry при скачивании agent.jar (3 попытки, exponential backoff);
- скрытием `JENKINS_*` переменных от дочернего Java-процесса;
- передачей секрета через `@file` (не в командной строке);
- отдельным модулем SSL-диагностики сертификата Jenkins-сервера;
- fallback URL для agent.jar (Nexus, Artifactory).

## Быстрый старт

### 1. Настройка окружения
```cmd
scripts\setup.bat
```
Создаёт `venv/` и устанавливает зависимости (PyQt5, requests, cryptography).

### 2. Настройка конфигурации
По умолчанию launcher использует `config\config.json`.

Если файла ещё нет, launcher создаст его из `config\config.template.json` при первом запуске.

Пример:
```json
{
  "agent": {
    "jenkinsUrl": "https://jenkins.example.com",
    "agentName": "windows-agent-1",
    "secret": "секрет_из_Jenkins_UI",
    "tunnel": "",
    "javaHome": ""
  }
}
```

### 3. Запуск (разработка)
```cmd
scripts\run-dev.bat
```

### 4. Сборка в .exe
```cmd
scripts\build.bat
```
Результат: `agent-launcher.exe` в корне репозитория.

Если `config\build.json` отсутствует, `scripts\build.bat` использует `config\build.template.json`.

## Структура проекта

```
jenkins-agent-launcher/
├── src/                          # Исходный код
│   ├── main.py                   # Точка входа (CLI → GUI/Console)
│   ├── config.py                 # Конфигурация, валидация
│   ├── logger.py                 # Логирование с ротацией
│   ├── ssl_check.py              # SSL-диагностика
│   ├── downloader.py             # Скачивание agent.jar (retry + progress)
│   ├── process.py                # Запуск Java, изоляция ENV
│   ├── agent_controller.py       # Оркестрация
│   └── gui/
│       ├── main_window.py        # GUI-форма + тёмная тема + hotkeys
│       ├── tray_icon.py          # Tray + уведомления
│       └── dialogs.py            # Справка, О программе
│
├── config/
│   ├── config.template.json      # Шаблон runtime-конфигурации
│   ├── config.json               # Runtime-конфигурация
│   ├── build.template.json       # Шаблон параметров сборки
│   └── build.json                # Параметры сборки
│
├── tests/                        # Тесты (14 файлов)
│   ├── test_config.py            # Валидная конфигурация
│   ├── test_config_breaking.py   # Битый JSON, null, unicode
│   ├── test_logger.py            # Запись, ротация, callback
│   ├── test_logger_breaking.py   # 100 потоков, 10MB, readonly
│   ├── test_downloader.py        # Retry, timeout, progress
│   ├── test_ssl_check.py         # Валидные/невалидные сертификаты
│   ├── test_process.py           # Запуск, изоляция ENV
│   ├── test_process_breaking.py  # Unicode, race, long secret
│   ├── test_agent_controller.py  # Полный цикл, crash, callback errors
│   ├── test_integration.py       # E2E: config → download → process
│   ├── test_transition.py        # Jenkins outage/recovery
│   ├── test_security.py          # Env injection, path traversal, race
│   └── test_main.py              # CLI парсинг
│
├── scripts/
│   ├── setup.bat                 # Создание venv + установка зависимостей
│   ├── run-dev.bat               # Запуск из venv (без консоли)
│   ├── build.bat                 # Сборка в .exe (PyInstaller)
│   └── _gen_version.py           # Генерация version script
│
├── docs/                         # Документация
│   ├── README.md                 # Навигация по документации
│   └── specification.md          # Спецификация приложения
│
├── assets/
│   └── jenkins.ico               # Иконка приложения
│
├── requirements.txt
├── pytest.ini
├── .gitignore
└── README.md                     # Этот файл
```

## Ключевые возможности

### GUI
| Функция | Горячая клавиша |
|---------|----------------|
| Перезапуск агента | `F5` |
| Остановка агента | `Ctrl+S` |
| Открыть лог | `Ctrl+L` |
| Переключить тему | `Ctrl+T` |
| Выход | `Ctrl+Q` |
| Справка | `F1` |

### Конфигурация
| Секция | Назначение |
|--------|-----------|
| `agent` | Подключение: url, name, secret, verifySsl, tunnel, javaHome, workDir |
| `logging` | Логи: dir, rotation (daily/weekly/never/size), maxDays, maxSizeMB |
| `download` | Скачивание: timeout, maxRetries, retryDelaySeconds, chunkSize |
| `fallback` | Резервный URL для agent.jar и политика `verifySsl` |
| `behavior` | Поведение: maxRestarts, restartDelaySeconds, autoUpdateJar |
| `update` | Автообновление: enabled, checkUrl, intervalHours |
| `environment` | Переменные окружения, которые launcher скроет от java-процесса, с причиной исключения |
| `ui` | Тема и поведение старта интерфейса, включая `startMinimized` |

### Источники конфигурации (по приоритету)
1. Значения по умолчанию
2. Файл `config/config.json`
3. Файл `config.json` для legacy-совместимости
4. Параметры командной строки (`--url`, `--name`, `--secret`, ...)
5. Переменные окружения (`JENKINS_SECRET`, `JENKINS_AGENT_NAME`, ...)

Для выбора Java используется отдельный порядок:

1. `agent.javaHome` или `--java-home`
2. `java` из `PATH`
3. системный `JAVA_HOME`

### Логирование
| Параметр | По умолчанию | Описание |
|----------|-------------|----------|
| `logging.dir` | `logs` | Директория логов |
| `logging.rotation` | `daily` | daily / weekly / never / size |
| `logging.maxDays` | `14` | Удалять файлы старше N дней |
| `logging.maxSizeMB` | `50` | При rotation=size: новый файл при превышении |
| `agent.logFileName` / `--log-path` | `logs\\jenkins-agent.log` | Базовый путь лог-файла; при ротации сохраняются директория и базовое имя |

### Безопасность
- ✅ `JENKINS_*` переменные **скрыты** от дочернего Java-процесса
- ✅ Секрет передаётся через **временный файл** (`@file`), не в CLI
- ✅ Файл секрета **перезаписывается нулями** перед удалением
- ✅ В кодовой базе есть модуль SSL-диагностики (`src/ssl_check.py`)
- ✅ Скачивание agent.jar: **3 retry** с exponential backoff

## Зависимости

**На машине разработчика:**
- Python 3.12+
- `scripts\setup.bat` — установит всё автоматически

**На целевой машине (для .exe):**
- Windows 10/11
- Java Runtime Environment (JRE 8+)
- **Никаких дополнительных зависимостей** (standalone .exe)

Если Java не находится в `PATH`, можно явно указать `agent.javaHome` в `config.json` или передать `--java-home`.

## Архитектура

```
┌─────────────────────────────────────────────────┐
│  Jenkins Agent Launcher (GUI / Console)          │
│                                                  │
│  ┌─────────────────────────────────────────────┐ │
│  │  AgentController                            │ │
│  │  1. Проверка Jenkins                        │ │
│  │  2. Скачивание agent.jar (retry ×3)         │ │
│  │  3. Проверка Java                           │ │
│  │  4. Запуск процесса → мониторинг → рестарт  │ │
│  └─────────────────────────────────────────────┘ │
│                                                  │
│  ┌──────────────┐  ┌──────────────────────────┐  │
│  │  Rotating    │  │  AgentProcess            │  │
│  │  Logger      │  │  • Изоляция JENKINS_*    │  │
│  │  • TSV-формат│  │  • Secret через @file    │  │
│  │  • Ротация   │  │  • Асинхронный вывод     │  │
│  └──────────────┘  └──────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Тесты

```cmd
venv\Scripts\pytest tests\ -v
```

В репозитории 14 тестовых файлов. Полный прогон зависит от прав на временные каталоги и кэш `pytest` в текущем окружении.

Для стабильного запуска на Windows рекомендуется использовать отдельный runner:

```cmd
scripts\run-tests.bat
```

Он:
- запускает `pytest` из `venv`;
- создаёт отдельный `--basetemp` для каждого запуска;
- по умолчанию использует temp-root в `%LOCALAPPDATA%\jenkins-agent-launcher\pytest`, а не общий sandbox/temp;
- делает best-effort cleanup ACL/readonly-хвостов после завершения.

Если нужно оставить временные каталоги для диагностики:

```powershell
.\scripts\run-tests.ps1 -KeepTemp
```

Если нужно явно запускать внутри workspace:

```powershell
.\scripts\run-tests.ps1 -UseWorkspaceTemp
```

## Документация

Актуальная документация: [`docs/README.md`](docs/README.md)

| Документ | Описание |
|----------|---------|
| [Спецификация](docs/specification.md) | Краткая спецификация текущего поведения |
| [Навигация](docs/README.md) | Какие документы поддерживаются сейчас |
