# Эксплуатация и релиз

Этот документ собирает подробности, которые важны для сопровождения `Jenkins Agent Launcher`, но перегружают корневой README.

## Как запускается агент

Основной сценарий выполняет `AgentController`:

1. читает и валидирует конфигурацию;
2. проверяет доступность Jenkins;
3. пытается подхватить уже запущенный подходящий Java-процесс;
4. скачивает `agent.jar`, если attach не состоялся и скачивание разрешено;
5. при необходимости использует fallback URL;
6. при включённом `jnlp.enabled` получает Jenkins secret из JNLP, если secret отсутствует или включён refresh;
7. ищет Java через `agent.javaHome` / `--java-home`, затем `PATH`, затем `JAVA_HOME`;
8. создаёт временный файл с Jenkins secret;
9. запускает `java -Djava.io.tmpdir=... -jar agent.jar ...`, если задан `agent.tempDir`;
10. пишет stdout/stderr агента в лог;
11. перезапускает агент по политике `behavior.maxRestarts`.

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
| `update` | metadata self-update и проверка publisher/hash |
| `environment` | переменные, удаляемые перед запуском Java |
| `ui` | тема и старт в свёрнутом виде |

## Скачивание agent.jar и fallback

Launcher скачивает `agent.jar` перед запуском, если файл отсутствует или включено обновление. Настройки находятся в секциях `download`, `fallback` и `behavior`.

Пример:

```json
{
  "download": {
    "timeout": 120,
    "maxRetries": 3,
    "retryDelaySeconds": 5,
    "chunkSize": 8192
  },
  "fallback": {
    "agentJarUrl": "https://downloads.example.com/jenkins/agent.jar",
    "verifySsl": true
  },
  "behavior": {
    "autoUpdateJar": true
  }
}
```

Цель fallback URL - дать контролируемый внутренний источник `agent.jar`, например artifact storage, Nexus, Artifactory или файловый gateway, если Jenkins временно недоступен.

## Временный каталог

`agent.tempDir` или `--temp-dir` задаёт каталог для временных файлов launcher и Java-процесса агента.

Поведение:

- относительный путь разрешается от корня launcher;
- абсолютный путь используется как есть;
- каталог создаётся перед созданием временного secret-файла;
- Java получает параметр `-Djava.io.tmpdir=<path>` до `-jar`;
- временный secret `@file` создаётся в этом же каталоге.

Пример:

```json
{
  "agent": {
    "tempDir": "runtime\\tmp"
  }
}
```

## Получение secret из JNLP

Если `jnlp.enabled=true`, launcher может получить Jenkins secret из JNLP-файла перед запуском Java-процесса. Если `jnlp.url` пустой, URL строится как:

```text
<jenkinsUrl>/computer/<agentName>/jenkins-agent.jnlp
```

Пример:

```json
{
  "agent": {
    "jenkinsUrl": "https://jenkins.example.com",
    "agentName": "windows-agent-1",
    "secret": ""
  },
  "jnlp": {
    "enabled": true,
    "url": "",
    "refreshSecret": false,
    "saveSecret": false
  }
}
```

Поведение:

- при `refreshSecret=false` JNLP загружается только если `agent.secret` пустой или содержит placeholder;
- при `refreshSecret=true` secret обновляется перед запуском агента;
- при `saveSecret=true` полученный secret записывается в `agent.secret` в runtime `config.json`;
- TLS-проверка для JNLP использует `agent.verifySsl`.

## Логирование и диагностика

Лог пишется до запуска Java-процесса и продолжает пополняться после старта агента. Это важно для случаев, когда агент ещё не успел запуститься, но проблема уже произошла: битый конфиг, недоступный Jenkins, ошибка скачивания, отсутствие Java, ошибка TLS или некорректный путь.

По умолчанию:

| Параметр | Значение |
|----------|----------|
| Директория | `logs` |
| Ротация | `daily` |
| Хранение | `14` дней |
| Size rotation | `50` MB при `rotation=size` |

Формат лога TSV-подобный, его удобно читать как текстом, так и импортировать в Excel.

## Метаданные сборки и издатель

Параметры упаковки лежат в `config\build.json`. Если файла нет, используется `config\build.template.json`.

Пример:

```json
{
  "outputExe": "agent-launcher.exe",
  "iconPath": "assets/jenkins.ico",
  "version": "0.0.1",
  "title": "Jenkins Agent Launcher",
  "company": "Jenkins Agent Launcher Contributors",
  "noConsole": true,
  "sta": true
}
```

`scripts\_gen_version.py` генерирует PyInstaller version resource. В `.exe` попадают:

- `CompanyName`;
- `FileDescription`;
- `FileVersion`;
- `OriginalFilename`;
- `ProductName`;
- `ProductVersion`;
- copyright string.

Эти поля видны в свойствах файла и помогают инвентаризации, но не делают бинарь доверенным для Windows.

Чтобы Windows показывала verified publisher и меньше ругалась при запуске, нужен Authenticode code signing отдельным release-шагом:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx agent-launcher.exe
signtool verify /pa /v agent-launcher.exe
```

PFX, private key, пароль сертификата и signing tokens нельзя хранить в репозитории. Их нужно брать из Windows certificate store, CI secret store, HSM-backed signing или корпоративного signing service.

## Установка на рабочую станцию

Базовый production rollout:

1. собрать и подписать `agent-launcher.exe`;
2. подготовить `config\config.json` из шаблона;
3. указать Jenkins URL, имя агента, work dir, TLS policy и restart policy;
4. передать Jenkins secret через утверждённый локальный secret process;
5. развернуть `.exe`, конфиг и необходимые assets;
6. настроить запуск в пользовательской сессии через корпоративный endpoint management.

Launcher не является Windows service. Он рассчитан на интерактивную пользовательскую сессию, чтобы были доступны tray icon, GUI и desktop notifications.

## Границы поддержки

Поддерживается:

- Windows 10/11 и Windows Server в интерактивной пользовательской сессии;
- Jenkins inbound agent через `agent.jar`;
- packaged `.exe`, собранный штатным `scripts\build.bat`;
- локальная JSON-конфигурация, CLI overrides и ENV overrides.

Не является целью по умолчанию:

- запуск как Windows service;
- хранение production secrets в репозитории;
- отключение TLS verification без явного решения в конфиге;
- устранение SmartScreen warnings без code signing и publisher reputation.
