# HTTP API

Состояние кода: 17.10.2026. [Оглавление](README.md) · [Настройки](CONFIGURATION.md) · [Архитектура](ARCHITECTURE.md).

Все пути начинаются с `/api`. JSON-запросы используют `Content-Type: application/json`. В demo/test доступны `/api/docs` и `/api/openapi.json`; в production они отключены. Точные поля и ограничения входных моделей — в [schemas.py](../src/fczhk/schemas.py), ответы и проверки прав — в соответствующих [маршрутах](../src/fczhk/routes).

## Общие правила

- Доступ «участник» требует `Authorization: Bearer <session_token>` и членства в сообществе. «Администратор» дополнительно проверяет числовой Telegram ID из конфигурации. Чужие черновики игр скрыты от обычного участника.
- Telegram-вход возвращает `token` и `player`. Браузерный вход сначала получает challenge с cookie, затем передаёт `id_token`; сервер проверяет origin, nonce, подпись, срок и членство. Logout отзывает только переданную сессию. Demo login существует только в demo и доступен с loopback.
- Изменения игры используют актуальную `version`, оценки/прогнозы и управление аукционом — свои ревизии согласно модели. После 409 загрузить данные заново; не повторять изменение автоматически поверх чужой версии.
- Время — ISO 8601 с часовым поясом. Дата пропуска — `YYYY-MM-DD`, непрошедшая пятница без созданной игры. Амплуа: `field` / `keeper`, команды: `white` / `black`.
- Прикладные ошибки возвращают `{"detail":"сообщение"}`; валидация 422 может содержать массив подробностей. 401 — нет действующей сессии, 403 — запрет доступа, 404 — нет доступного ресурса, 409 — конфликт состояния/версии, 429 — лимит входа (`Retry-After: 60`), 503 — недоступность БД либо degraded readiness. Ошибки правил могут иметь код 400. Ответы `/api` не кешируются браузером.

## Каталог маршрутов

В колонке «Тело» указана модель JSON-запроса; `—` означает отсутствие JSON-тела. Query-параметры архива и специальные заголовки описаны ниже. Права капитана и ограничения конкретного состояния дополнительно проверяются бизнес-правилами.

### Вход

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| POST | `/api/auth/telegram` | Без сессии | Login |
| GET | `/api/auth/options` | Без сессии | — |
| POST | `/api/auth/telegram/browser/challenge` | Без сессии | — |
| POST | `/api/auth/telegram/browser` | Без сессии | BrowserLogin |
| POST | `/api/auth/logout` | Текущий Bearer | — |
| POST | `/api/auth/demo/{role}` | Только demo/loopback | — |

### Игроки и рейтинги

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| GET | `/api/me` | Участник | — |
| PATCH | `/api/me` | Участник | Name |
| GET | `/api/players` | Участник | — |
| GET | `/api/game-ratings` | Участник | — |
| GET | `/api/leaderboards` | Участник | — |
| GET | `/api/players/{player_id}/ratings/{position}` | Участник | — |
| GET | `/api/players/{player_id}/stats` | Участник | — |
| PUT | `/api/players/{player_id}/ratings` | Участник | RatingEdit |
| POST | `/api/players/guests` | Администратор | Name |
| POST | `/api/players/{guest_id}/link` | Администратор | LinkGuest |
| GET | `/api/me/profile-claim` | Участник | — |
| POST | `/api/me/profile-claim` | Участник | ClaimProfile |
| GET | `/api/profile-claims` | Администратор | — |
| POST | `/api/profile-claims/{player_id}/resolve` | Администратор | ResolveClaim |

### Игры и составы

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| GET | `/api/matches` | Участник | — |
| GET | `/api/matches/current` | Участник | — |
| GET | `/api/matches/{match_id}` | Участник | — |
| POST | `/api/matches` | Администратор | GameFields |
| PUT | `/api/matches/{match_id}` | Администратор | GameEdit |
| POST | `/api/matches/{match_id}/actions/{action}` | Администратор | Version |
| POST | `/api/matches/{match_id}/cancel` | Администратор | Cancellation |
| POST | `/api/matches/{match_id}/join` | Участник | Join |
| DELETE | `/api/matches/{match_id}/join` | Участник | — |
| PUT | `/api/matches/{match_id}/registrations/{reg_id}/payment` | Администратор | Payment |
| POST | `/api/matches/{match_id}/registrations/{reg_id}/remove` | Администратор | Version |
| POST | `/api/matches/{match_id}/participants` | Администратор | Include |
| POST | `/api/matches/{match_id}/promote` | Администратор | Promote |
| PUT | `/api/matches/{match_id}/teams` | Администратор | Teams |
| POST | `/api/matches/{match_id}/teams/swap-colors` | Администратор | Version |
| GET | `/api/matches/{match_id}/history` | Администратор | — |

### Автоматический подбор

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| PUT | `/api/matches/{match_id}/registrations/{reg_id}/rating` | Администратор | MatchRatingEdit |
| GET | `/api/balance/settings` | Администратор | — |
| POST | `/api/matches/{match_id}/balance` | Администратор | BalanceGenerate |
| GET | `/api/matches/{match_id}/balance` | Администратор | — |
| POST | `/api/matches/{match_id}/balance/{run_id}/apply` | Администратор | BalanceApply |

### Результаты, аукцион и прогнозы

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| GET | `/api/predictions/standings` | Участник | — |
| GET | `/api/matches/{match_id}/predictions` | Участник | — |
| PUT | `/api/matches/{match_id}/prediction` | Участник | PredictionEdit |
| GET | `/api/matches/{match_id}/result` | Участник | — |
| PUT | `/api/matches/{match_id}/result` | Администратор | ResultEdit |
| GET | `/api/matches/{match_id}/auction` | Участник | — |
| GET | `/api/matches/{match_id}/auctions/history` | Участник | — |
| POST | `/api/matches/{match_id}/auction` | Администратор | AuctionStart |
| POST | `/api/matches/{match_id}/auction/bids` | Участник | AuctionBid |
| POST | `/api/matches/{match_id}/auction/control` | Администратор | AuctionControl |

### Администрирование и диагностика

| Метод | Путь | Доступ | Тело |
| --- | --- | --- | --- |
| GET | `/api/template` | Администратор | — |
| PUT | `/api/template` | Администратор | TemplateEdit |
| POST | `/api/publications/{pub_id}/retry` | Администратор | — |
| POST | `/api/telegram/webhook` | Секрет webhook | Telegram Update |
| GET | `/api/schedule/skipped` | Администратор | — |
| POST | `/api/schedule/skipped` | Администратор | SkipDay |
| DELETE | `/api/schedule/skipped/{day}` | Администратор | — |
| GET | `/api/operations` | Администратор | — |
| GET | `/api/health/ready` | Без сессии | — |
| GET | `/api/metrics` | Токен метрик | — |
| POST | `/api/publications/{pub_id}/retry-stale` | Администратор | — |
| GET | `/api/health` | Без сессии | — |

## Форматы чтения и важные операции

`GET /api/matches?limit=20&offset=0` возвращает массив кратких карточек, без общего `total` и без полных заявок/составов. `limit` от 1 до 100, `offset` от 0; порядок — начало и ID по убыванию. Карточка содержит `id`, `starts_at`, `game_day`, `location`, `historical`, `status`, `version`, `participant_count`, `result` (null либо `completed` и `score.white/black`). Клиент загружает следующую страницу; пустая страница означает конец.

`GET /api/matches/current` возвращает полную ближайшую будущую неотменённую игру, иначе последнюю неотменённую, либо null. Администратору доступны также черновики. `GET /api/matches/{match_id}` — полная карточка выбранной игры. Получение архива больше не заменяет получение полной карточки: клиентам прежнего API необходимо использовать detail endpoint.

`POST /api/matches/{match_id}/actions/{action}` поддерживает `open`, `finalize`, `approve`, `publish`, тело `{"version":7}`. Версию брать из последнего ответа, а не из примера. Публикация ставится в очередь; успешный HTTP-ответ не означает доставку в Telegram.

Отмена: `POST /api/matches/{match_id}/cancel`, например `{"version":7,"reason":"Манеж закрыт"}`. Только до начала и без результата; причина 2–300 символов. Сохраняются заявки, оплаты и аудит; активный аукцион прекращает принимать ставки, прогнозы закрываются. Уведомление отправляется для уже открытого сбора, отмена черновика не публикуется.

Пропуск пятницы: `POST /api/schedule/skipped` с `{"game_day":"2026-10-23","reason":"Манеж закрыт"}`. Использовать фактическую подходящую дату. Если игра уже создана, нужна отмена игры. Пропуск блокирует автоматическое и ручное создание и перенос на эту дату. DELETE снимает исключение; расписание снова может создать игру в своём окне. Список возвращает последние 100 исключений.

Заявка на историю: `POST /api/me/profile-claim` с `{"guest_id":123}`. Решение администратора: `POST /api/profile-claims/{player_id}/resolve` с `{"guest_id":123,"accept":true}`. ID примеров заменять реальными. Подтверждение объединяет историю, отклоняет конкурирующие заявки и блокируется при конфликтующем участии в одной игре. Поиск по имени не подтверждает личность.

`GET /api/leaderboards` возвращает результаты и средние сообщества, `/api/game-ratings` — экспериментальный OpenSkill. Поиск и порог числа игр применяются frontend; это не query-параметры данных endpoints. Профиль возвращает историю/партнёров, интерфейс первоначально раскрывает пять игр и трёх партнёров.

## Служебный доступ

`/api/telegram/webhook` принимает `X-Telegram-Bot-Api-Secret-Token`, совпадающий с `FCZHK_WEBHOOK_SECRET`; пользовательская сессия не заменяет этот секрет. `/api/metrics` требует `Authorization: Bearer <FCZHK_METRICS_TOKEN>`; пустое значение отключает доступ (403). Это текст Prometheus, не JSON.

`/api/health` проверяет БД. `/api/health/ready` возвращает `status` и булев `worker`, с 503 при проблеме. Детальная очередь и ошибки доступны только администратору через `/api/operations`. Перед `/api/publications/{pub_id}/retry` для `uncertain` проверить чат: повтор может создать дубль. `/retry-stale` повторяет пометку старого доставленного поста. Оба действия журналируются.
