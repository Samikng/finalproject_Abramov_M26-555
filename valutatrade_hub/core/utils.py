"""Вспомогательные функции: валидация, форматирование, работа со временем, кеш."""

import math
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from valutatrade_hub.core.currencies import CURRENCY_CODE_PATTERN, is_crypto_code

CRYPTO_DECIMALS = 4
FIAT_DECIMALS = 2


# --- Валидация ---------------------------------------------------------------


def normalize_currency_code(code: Any) -> str:
    """Проверить формат кода валюты и привести его к верхнему регистру.

    Raises:
        ValueError: пустая строка или неверный формат.
    """
    if not isinstance(code, str) or not code.strip():
        raise ValueError("Код валюты должен быть непустой строкой")
    normalized = code.strip().upper()
    if not CURRENCY_CODE_PATTERN.match(normalized):
        raise ValueError(
            f"Некорректный код валюты '{code}': ожидается 2–5 символов без пробелов"
        )
    return normalized


def validate_amount(amount: Any) -> float:
    """Проверить, что сумма — конечное положительное число, и вернуть float.

    Raises:
        ValueError: если сумма не положительное число.
    """
    error = ValueError("'amount' должен быть положительным числом")
    if isinstance(amount, bool):
        raise error
    try:
        value = float(amount)
    except (TypeError, ValueError):
        raise error from None
    if not math.isfinite(value) or value <= 0:
        raise error
    return value


# --- Форматирование ----------------------------------------------------------


def format_amount(code: str, amount: float) -> str:
    """Баланс/количество: 4 знака для криптовалют, 2 — для фиата."""
    decimals = CRYPTO_DECIMALS if is_crypto_code(code) else FIAT_DECIMALS
    return f"{amount:.{decimals}f}"


def format_money(value: float) -> str:
    """Денежная сумма с разделителем тысяч: ``3,329.00``."""
    return f"{value:,.2f}"


def format_rate(rate: float) -> str:
    """Курс с точностью, зависящей от порядка величины."""
    if rate >= 100:
        return f"{rate:.2f}"
    if rate >= 1:
        return f"{rate:.4f}"
    text = f"{rate:.8f}".rstrip("0")
    return text if not text.endswith(".") else text + "0"


# --- Время -------------------------------------------------------------------


def utc_now_iso() -> str:
    """Текущее время UTC в ISO-формате с суффиксом Z (без микросекунд)."""
    return datetime.now(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(timestamp: str) -> datetime:
    """Разобрать ISO-строку; время без часового пояса считается UTC."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def age_seconds(timestamp: str) -> float:
    """Сколько секунд прошло с момента ``timestamp``."""
    return (datetime.now(UTC) - parse_iso(timestamp)).total_seconds()


def format_timestamp(timestamp: str | None) -> str:
    """ISO-время → ``YYYY-MM-DD HH:MM:SS`` для вывода пользователю."""
    if not timestamp:
        return "—"
    try:
        return parse_iso(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return timestamp


# --- Кеширование (замыкание) -------------------------------------------------


def make_mtime_cache(loader: Callable[[Path], Any]) -> Callable[[Path], Any]:
    """Обернуть загрузчик файла кешем, который сбрасывается при изменении файла.

    Состояние (последний mtime и результат) хранится в замыкании, поэтому
    повторные чтения неизменённого файла не обращаются к диску.
    У возвращаемой функции есть метод ``invalidate()`` для ручного сброса.
    """
    cache: dict[Path, tuple[float, Any]] = {}

    def cached(path: Path) -> Any:
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            cache.pop(path, None)
            return loader(path)
        hit = cache.get(path)
        if hit is not None and hit[0] == mtime:
            return hit[1]
        value = loader(path)
        cache[path] = (mtime, value)
        return value

    def invalidate() -> None:
        cache.clear()

    cached.invalidate = invalidate  # type: ignore[attr-defined]
    return cached
