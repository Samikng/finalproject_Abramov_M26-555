"""Настройка логирования.

Формат: человекочитаемая строка ``LEVEL ISO-время сообщение``, например::

    INFO 2025-10-09T12:05:22 BUY user='alice' currency='BTC' amount=0.0500 ...

Файлы (в каталоге log_dir из SettingsLoader):
    actions.log — доменные операции (@log_action);
    parser.log  — работа Parser Service.
Ротация: RotatingFileHandler по размеру (log_max_bytes, log_backup_count).
Уровень по умолчанию — INFO (log_level), для отладки можно указать DEBUG.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

ACTIONS_LOGGER = "valutatrade.actions"
PARSER_LOGGER = "valutatrade.parser"
APP_LOGGER = "valutatrade"

_configured = False


def _file_handler(filename: str, formatter: logging.Formatter) -> logging.Handler:
    settings = SettingsLoader()
    log_dir = settings.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / filename,
        maxBytes=int(settings.get("log_max_bytes")),
        backupCount=int(settings.get("log_backup_count")),
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    return handler


def setup_logging(console: bool = True) -> None:
    """Сконфигурировать логгеры приложения (повторный вызов ничего не делает).

    Args:
        console: дублировать сообщения Parser Service в консоль
            (``INFO: Fetching from CoinGecko... OK``).
    """
    global _configured
    if _configured:
        return
    settings = SettingsLoader()
    level = getattr(logging, str(settings.get("log_level")).upper(), logging.INFO)
    formatter = logging.Formatter(
        settings.get("log_format"), datefmt=settings.get("log_date_format")
    )

    app_logger = logging.getLogger(APP_LOGGER)
    app_logger.setLevel(level)
    app_logger.propagate = False
    app_logger.addHandler(_file_handler("app.log", formatter))

    actions_logger = logging.getLogger(ACTIONS_LOGGER)
    actions_logger.setLevel(level)
    actions_logger.propagate = False
    actions_logger.addHandler(_file_handler("actions.log", formatter))

    parser_logger = logging.getLogger(PARSER_LOGGER)
    parser_logger.setLevel(level)
    parser_logger.propagate = False
    parser_logger.addHandler(_file_handler("parser.log", formatter))
    if console:
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        parser_logger.addHandler(stream)

    _configured = True
