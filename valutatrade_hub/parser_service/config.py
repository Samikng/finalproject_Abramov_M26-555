"""Конфигурация Parser Service: API, списки валют, пути и сетевые параметры.

API-ключ ExchangeRate-API не хранится в коде: он читается из переменной
окружения ``EXCHANGERATE_API_KEY`` или из файла ``.env`` в корне проекта
(файл исключён из git через .gitignore).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader

API_KEY_ENV = "EXCHANGERATE_API_KEY"


def _read_dotenv(path: Path) -> dict[str, str]:
    """Минимальный разбор .env: строки ``KEY=VALUE``, # — комментарии."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def load_api_key() -> str | None:
    """Ключ из окружения, иначе из .env; None, если ключ не задан."""
    key = os.getenv(API_KEY_ENV)
    if not key:
        key = _read_dotenv(SettingsLoader().project_root / ".env").get(API_KEY_ENV)
    return key or None


@dataclass(frozen=True)
class ParserConfig:
    """Все изменяемые параметры Parser Service в одном месте."""

    EXCHANGERATE_API_KEY: str | None = field(default_factory=load_api_key)

    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )

    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().data_path("rates_file")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().data_path("history_file")
    )

    REQUEST_TIMEOUT: int = 10

    UPDATE_INTERVAL_SECONDS: int = 300
