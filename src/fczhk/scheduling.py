from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import GameTemplate

MOSCOW = ZoneInfo("Europe/Moscow")
WEEKDAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def schedule_window(template: GameTemplate, at: datetime) -> tuple[datetime, datetime]:
    """Return the current collection window, or the next one if its game has started."""
    local = at.astimezone(MOSCOW)
    day = local.date() - timedelta(days=(local.weekday() - template.opening_weekday) % 7)
    hour, minute = map(int, template.opening_time.split(":"))
    opening = datetime.combine(day, datetime.min.time(), MOSCOW).replace(hour=hour, minute=minute)
    if opening > local:
        opening -= timedelta(days=7)
    game_day = opening.date() + timedelta(
        days=(template.game_weekday - template.opening_weekday) % 7
    )
    hour, minute = map(int, template.start_time.split(":"))
    starts = datetime.combine(game_day, datetime.min.time(), MOSCOW).replace(
        hour=hour, minute=minute
    )
    if local >= starts:
        opening += timedelta(days=7)
        starts += timedelta(days=7)
    return opening, starts


def schedule_description(template: GameTemplate) -> str:
    opening = f"Сбор: {WEEKDAYS[template.opening_weekday]}, {template.opening_time} МСК."
    game = f"Игра: {WEEKDAYS[template.game_weekday]}, {template.start_time} МСК."
    if not template.enabled:
        opening = "Автоматическое открытие сбора выключено."
    return f"{opening}\n{game}"
