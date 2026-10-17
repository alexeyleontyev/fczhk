# Конфигурация и CLI

[Оглавление](README.md) · [Первый запуск и эксплуатация](DEPLOYMENT_PLAN.md).

Настройки читает [Settings](../src/fczhk/config.py) из окружения и `.env`; переменные окружения имеют приоритет. Образец — [.env.example](../.env.example). Значения ниже — значения по умолчанию в коде, а не готовая production-конфигурация. `.env` не коммитится; на сервере установить права 0600.

## Приложение

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `FCZHK_ENV` | `production` | `production`, `demo` или `test`; демо не размещать публично |
| `FCZHK_DATABASE_URL` | `sqlite:///./.local/fczhk.db` | В production обязателен PostgreSQL; в Compose хост `db:5432` |
| `FCZHK_BOT_TOKEN` | пусто | Токен бота; обязателен в production |
| `FCZHK_BOT_USERNAME` | пусто | Username для прямых ссылок на игру в Mini App |
| `FCZHK_COMMUNITY_CHAT_ID` | пусто | Единственное разрешённое сообщество; обязательно в production |
| `FCZHK_PUBLICATION_CHAT_ID` | пусто | Чат/канал для постов; настроить до включения расписания |
| `FCZHK_ADMIN_IDS` | пусто | Числовые Telegram ID через запятую; хотя бы один в production |
| `FCZHK_PUBLIC_URL` | `http://localhost:8000` | В production HTTPS; совпадает с адресом Mini App и браузерного входа |
| `FCZHK_TELEGRAM_LOGIN_CLIENT_ID` | `0` | Client ID BotFather; 0 отключает вход в браузере |
| `FCZHK_WEBHOOK_SECRET` | пусто | Проверка секретного заголовка webhook; пустое значение означает polling |
| `FCZHK_AUTH_MAX_AGE_SECONDS` | `300` | Максимальный возраст Telegram initData при входе |
| `FCZHK_SESSION_HOURS` | `12` | Срок сессии приложения |
| `FCZHK_MEMBERSHIP_CACHE_SECONDS` | `300` | Интервал перепроверки членства активной сессии |
| `FCZHK_MIN_FIELD_PLAYERS` | `2` | Минимум полевых при утверждении |
| `FCZHK_REQUIRE_TWO_KEEPERS` | `false` | Требовать двух вратарей; иначе разрешён явный недобор |
| `FCZHK_AUTH_IP_LIMIT` | `30` | Попыток входа с IP за минутное окно, минимум 1 |
| `FCZHK_AUTH_GLOBAL_LIMIT` | `300` | Попыток входа на процесс за окно, минимум 1 |
| `FCZHK_WORKER_STALE_SECONDS` | `120` | Порог устаревания heartbeat, минимум 30 |
| `FCZHK_PUBLICATION_STALE_SECONDS` | `300` | Порог задержки очереди/отправки, минимум 30 |
| `FCZHK_METRICS_TOKEN` | пусто | Отдельный Bearer для Prometheus; пусто отключает доступ |
| `FCZHK_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Доверенные прокси Uvicorn; Compose задаёт `*` при закрытом порте API |

Проверка production-настроек требует Telegram token, сообщество, администраторов, HTTPS и PostgreSQL. Username, публикационный чат, webhook и browser Client ID дополнительно проверяются оператором для выбранного режима. Смена `.env` требует перезапуска процессов, в Compose — пересоздания контейнеров. Не публиковать API напрямую при доверии ко всем forwarded-заголовкам.

Параметры самой игры и расписания находятся в БД и редактируются администратором в приложении: место, начало, цена, реквизиты и включение шаблона. Часовой пояс расписания — `Europe/Moscow`; шаблон изначально выключен. Пропуск конкретной пятницы хранится отдельно от шаблона.

## Compose и резервные копии

| Переменная | Назначение |
| --- | --- |
| `POSTGRES_PASSWORD` | Настоящий пароль PostgreSQL; в URL использовать его URL-encoded значение. Смена переменной не меняет пароль существующего volume |
| `DOMAIN` | Домен Caddy; DNS направлен на сервер, порты 80/443 открыты |
| `FCZHK_IMAGE` | Образ приложения; успешный deploy сохраняет разрешённый digest в `.local/release-image`, который использует `scripts/compose.sh` |
| `BACKUP_DIRECTORY` | Абсолютный каталог локальных backup для offsite-скрипта |
| `BACKUP_REMOTE` | SSH-назначение вида `user@host:/absolute/directory` |
| `FCZHK_TEST_DATABASE_URL` | Отдельное подключение для PostgreSQL-тестов; не production |

`BACKUP_DIRECTORY` и `BACKUP_REMOTE` задаются systemd через `/etc/fczhk-backup.env`. Расписание, проверка SSH host key, место хранения, оповещения и retention описаны в [эксплуатации](DEPLOYMENT_PLAN.md). Локальный пароль Compose `local-development-only` допустим только для разработки.

## Команды

В исходном checkout: `uv sync --locked`, затем `uv run fczhk COMMAND`. В production использовать wrapper Compose, сохраняющий выбранный образ.

| Команда | Действие |
| --- | --- |
| `demo` | Локальный интерфейс, SQLite и имитация публикаций; реальные токены не используются |
| `serve` | API и статический frontend, без применения миграций |
| `migrate` | Alembic upgrade до текущей схемы |
| `worker` | Расписание, доставка, heartbeat и очистка сессий |
| `demo-worker` | Отдельный worker с имитацией доставки для демо |
| `bot` | Приём Telegram updates через polling |
| `configure-bot` | Меняет команды, меню и webhook в Telegram; в polling-режиме удаляет webhook |
| `worker-health` | Проверяет свежесть heartbeat; ненулевой exit code при проблеме |
| `check-bot` | Читает webhook info без изменения настроек; проверяет URL и ошибки последних 5 минут; только webhook-режим |

`--port` задаёт порт сервера (8000 по умолчанию), `--once` запускает один проход worker. Полный список: `uv run fczhk --help`. Polling и webhook одновременно не запускать; публикации в обоих случаях требуют worker.
