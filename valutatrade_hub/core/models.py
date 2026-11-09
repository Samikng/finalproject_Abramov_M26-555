"""Доменные модели: пользователь (User), кошелёк (Wallet) и портфель (Portfolio)."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import datetime
from typing import Any

from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import (
    format_amount,
    normalize_currency_code,
    validate_amount,
)

MIN_PASSWORD_LENGTH = 4
SALT_BYTES = 8

DEFAULT_RATES_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 1.0786,
    "GBP": 1.2361,
    "RUB": 0.01016,
    "BTC": 59337.21,
    "ETH": 3720.0,
    "SOL": 145.12,
}

RateProvider = Callable[[str, str], float]


def hash_password(password: str, salt: str) -> str:
    """Односторонний хеш: SHA-256(password + salt)."""
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()


def _validate_password(password: Any) -> str:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")
    return password


class User:
    """Пользователь системы. Пароль хранится только в виде соли и хеша."""

    def __init__(
        self,
        user_id: int,
        username: str,
        hashed_password: str,
        salt: str,
        registration_date: datetime,
    ) -> None:
        if not isinstance(user_id, int) or user_id <= 0:
            raise ValueError("user_id должен быть положительным целым числом")
        self._user_id = user_id
        self._username = ""
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, user_id: int, username: str, password: str) -> User:
        """Создать нового пользователя: сгенерировать соль и захешировать пароль."""
        _validate_password(password)
        salt = secrets.token_hex(SALT_BYTES)
        return cls(
            user_id=user_id,
            username=username,
            hashed_password=hash_password(password, salt),
            salt=salt,
            registration_date=datetime.now().replace(microsecond=0),
        )

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def username(self) -> str:
        return self._username

    @username.setter
    def username(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        return self._hashed_password

    @property
    def salt(self) -> str:
        return self._salt

    @property
    def registration_date(self) -> datetime:
        return self._registration_date

    def get_user_info(self) -> str:
        """Информация о пользователе без пароля и соли."""
        return (
            f"Пользователь #{self._user_id}: {self._username}, "
            f"зарегистрирован {self._registration_date.isoformat(sep=' ')}"
        )

    def change_password(self, new_password: str) -> None:
        """Сменить пароль: новая соль + новый хеш."""
        _validate_password(new_password)
        self._salt = secrets.token_hex(SALT_BYTES)
        self._hashed_password = hash_password(new_password, self._salt)

    def verify_password(self, password: str) -> bool:
        """Проверить пароль (сравнение хешей за постоянное время)."""
        if not isinstance(password, str):
            return False
        candidate = hash_password(password, self._salt)
        return secrets.compare_digest(candidate, self._hashed_password)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "username": self._username,
            "hashed_password": self._hashed_password,
            "salt": self._salt,
            "registration_date": self._registration_date.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> User:
        return cls(
            user_id=int(data["user_id"]),
            username=data["username"],
            hashed_password=data["hashed_password"],
            salt=data["salt"],
            registration_date=datetime.fromisoformat(data["registration_date"]),
        )

    def __repr__(self) -> str:
        return f"User(user_id={self._user_id}, username={self._username!r})"


class Wallet:
    """Кошелёк пользователя в одной конкретной валюте."""

    def __init__(self, currency_code: str, balance: float = 0.0) -> None:
        self.currency_code = normalize_currency_code(currency_code)
        self._balance = 0.0
        self.balance = balance

    @property
    def balance(self) -> float:
        """Текущий баланс."""
        return self._balance

    @balance.setter
    def balance(self, value: float) -> None:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise TypeError("Баланс должен быть числом")
        if value < 0:
            raise ValueError("Баланс не может быть отрицательным")
        self._balance = float(value)

    def deposit(self, amount: float) -> None:
        """Пополнить баланс на положительную сумму."""
        self.balance = self._balance + validate_amount(amount)

    def withdraw(self, amount: float) -> None:
        """Списать сумму, если хватает средств.

        Raises:
            ValueError: сумма не положительна.
            InsufficientFundsError: сумма больше баланса.
        """
        value = validate_amount(amount)
        if value > self._balance:
            raise InsufficientFundsError(
                available=self._balance, required=value, code=self.currency_code
            )
        self.balance = self._balance - value

    def get_balance_info(self) -> str:
        """Строка вида ``BTC: 0.0500``."""
        code = self.currency_code
        return f"{code}: {format_amount(code, self._balance)}"

    def to_dict(self) -> dict[str, Any]:
        return {"currency_code": self.currency_code, "balance": self._balance}

    def __repr__(self) -> str:
        return f"Wallet({self.currency_code!r}, balance={self._balance})"


class Portfolio:
    """Все кошельки одного пользователя."""

    def __init__(
        self,
        user_id: int,
        wallets: dict[str, Wallet] | None = None,
        user: User | None = None,
    ) -> None:
        self._user_id = user_id
        self._wallets: dict[str, Wallet] = dict(wallets or {})
        self._user = user

    @property
    def user_id(self) -> int:
        return self._user_id

    @property
    def user(self) -> User | None:
        """Владелец портфеля (только чтение)."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Копия словаря кошельков: внешний код не может изменить состав."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Добавить пустой кошелёк. Код валюты должен быть уникален в портфеле."""
        code = normalize_currency_code(currency_code)
        if code in self._wallets:
            raise ValueError(f"Кошелёк '{code}' уже есть в портфеле")
        wallet = Wallet(code)
        self._wallets[code] = wallet
        return wallet

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Кошелёк по коду валюты или None."""
        return self._wallets.get(normalize_currency_code(currency_code))

    def get_or_create_wallet(self, currency_code: str) -> Wallet:
        """Вернуть кошелёк, создав его при отсутствии."""
        return self.get_wallet(currency_code) or self.add_currency(currency_code)

    def get_total_value(
        self, base_currency: str = "USD", rate_provider: RateProvider | None = None
    ) -> float:
        """Общая стоимость всех кошельков в ``base_currency``.

        Args:
            base_currency: валюта, в которой считается итог.
            rate_provider: функция ``(from_code, to_code) -> rate``; если не
                задана, используются фиксированные курсы DEFAULT_RATES_TO_USD.
        """
        base = normalize_currency_code(base_currency)
        provider = rate_provider or _default_rate_provider
        total = 0.0
        for code, wallet in self._wallets.items():
            if wallet.balance == 0:
                continue
            rate = 1.0 if code == base else provider(code, base)
            total += wallet.balance * rate
        return total

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self._user_id,
            "wallets": {code: w.to_dict() for code, w in self._wallets.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], user: User | None = None) -> Portfolio:
        wallets = {
            code: Wallet(raw.get("currency_code", code), raw.get("balance", 0.0))
            for code, raw in data.get("wallets", {}).items()
        }
        return cls(int(data["user_id"]), wallets, user)


def _default_rate_provider(from_code: str, to_code: str) -> float:
    try:
        return DEFAULT_RATES_TO_USD[from_code] / DEFAULT_RATES_TO_USD[to_code]
    except KeyError as missing:
        raise ValueError(f"Нет фиксированного курса для {missing}") from None
