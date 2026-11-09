"""Иерархия валют (наследование и полиморфизм) и реестр поддерживаемых валют."""

import re
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError

# Код валюты: верхний регистр, 2–5 символов, без пробелов.
CURRENCY_CODE_PATTERN = re.compile(r"^[A-Z0-9]{2,5}$")


class Currency(ABC):
    """Абстрактная валюта с единым интерфейсом отображения.

    Инварианты:
        code — верхний регистр, 2–5 символов, без пробелов;
        name — непустая строка.
    """

    def __init__(self, name: str, code: str) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        if not isinstance(code, str) or not CURRENCY_CODE_PATTERN.match(code):
            raise ValueError(
                f"Некорректный код валюты '{code}': "
                "ожидается 2–5 символов в верхнем регистре без пробелов"
            )
        self.name = name.strip()
        self.code = code

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть строковое представление валюты для UI и логов."""

    @property
    def is_crypto(self) -> bool:
        """Является ли валюта криптовалютой."""
        return False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r}, name={self.name!r})"


class FiatCurrency(Currency):
    """Фиатная валюта, выпускаемая государством или валютным союзом."""

    def __init__(self, name: str, code: str, issuing_country: str) -> None:
        super().__init__(name, code)
        if not issuing_country or not issuing_country.strip():
            raise ValueError("Страна эмиссии не может быть пустой")
        self.issuing_country = issuing_country.strip()

    def get_display_info(self) -> str:
        """Пример: ``[FIAT] USD — US Dollar (Issuing: United States)``."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом консенсуса и рыночной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float):
        super().__init__(name, code)
        if not algorithm or not algorithm.strip():
            raise ValueError("Алгоритм криптовалюты не может быть пустым")
        if market_cap < 0:
            raise ValueError("Капитализация не может быть отрицательной")
        self.algorithm = algorithm.strip()
        self.market_cap = float(market_cap)

    @property
    def is_crypto(self) -> bool:
        return True

    def get_display_info(self) -> str:
        """Пример: ``[CRYPTO] BTC — Bitcoin (Algo: SHA-256, MCAP: 1.12e12)``."""
        mcap = f"{self.market_cap:.2e}".replace("e+", "e")
        return (
            f"[CRYPTO] {self.code} — {self.name} (Algo: {self.algorithm}, MCAP: {mcap})"
        )


_REGISTRY: dict[str, Currency] = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("British Pound", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        FiatCurrency("Japanese Yen", "JPY", "Japan"),
        FiatCurrency("Chinese Yuan", "CNY", "China"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256", 1.12e12),
        CryptoCurrency("Ethereum", "ETH", "Ethash", 4.5e11),
        CryptoCurrency("Solana", "SOL", "Proof of History", 6.8e10),
    )
}


def get_currency(code: str) -> Currency:
    """Фабрика: вернуть объект валюты по коду.

    Код нормализуется (обрезка пробелов, верхний регистр).
    Raises:
        CurrencyNotFoundError: если код не зарегистрирован.
    """
    normalized = code.strip().upper() if isinstance(code, str) else ""
    try:
        return _REGISTRY[normalized]
    except KeyError:
        raise CurrencyNotFoundError(normalized or str(code)) from None


def supported_codes() -> list[str]:
    """Список поддерживаемых кодов валют (по алфавиту)."""
    return sorted(_REGISTRY)


def is_crypto_code(code: str) -> bool:
    """True, если код принадлежит зарегистрированной криптовалюте."""
    currency = _REGISTRY.get(code)
    return currency is not None and currency.is_crypto
