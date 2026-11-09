"""Пользовательские (доменные) исключения ValutaTrade Hub.

Все исключения наследуются от ValutaTradeError, поэтому CLI может перехватывать
их единообразно и печатать ``str(error)`` как дружелюбное сообщение.

Точки возникновения:
    InsufficientFundsError — Wallet.withdraw(), usecases.buy()/sell();
    CurrencyNotFoundError  — currencies.get_currency(), валидация в get_rate();
    ApiRequestError        — parser_service.api_clients / updater;
    RateUnavailableError   — usecases.get_rate(), если курса нет и обновить не удалось.
"""


class ValutaTradeError(Exception):
    """Базовое исключение приложения."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class InsufficientFundsError(ValutaTradeError):
    """Недостаточно средств на кошельке."""

    def __init__(self, available: float, required: float, code: str) -> None:
        # Ленивый импорт: utils зависит от currencies, а currencies — от exceptions.
        from valutatrade_hub.core.utils import format_amount

        self.available = available
        self.required = required
        self.code = code
        super().__init__(
            f"Недостаточно средств: доступно {format_amount(code, available)} {code}, "
            f"требуется {format_amount(code, required)} {code}"
        )


class CurrencyNotFoundError(ValutaTradeError):
    """Неизвестный код валюты."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class UnknownBaseCurrencyError(CurrencyNotFoundError):
    """Неизвестная базовая валюта (для show-portfolio)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.message = f"Неизвестная базовая валюта '{code}'"


class ApiRequestError(ValutaTradeError):
    """Сбой обращения к внешнему API."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")


class RateUnavailableError(ApiRequestError):
    """Курс не найден в кеше и не может быть получен от Parser Service."""

    def __init__(self, from_code: str, to_code: str, message: str | None = None):
        super().__init__(f"нет курса {from_code}→{to_code}")
        self.from_code = from_code
        self.to_code = to_code
        self.message = (
            message
            or f"Курс {from_code}→{to_code} недоступен. Повторите попытку позже."
        )


class UserAlreadyExistsError(ValutaTradeError):
    """Имя пользователя уже занято."""

    def __init__(self, username: str) -> None:
        super().__init__(f"Имя пользователя '{username}' уже занято")


class UserNotFoundError(ValutaTradeError):
    """Пользователь не найден."""

    def __init__(self, username: str) -> None:
        super().__init__(f"Пользователь '{username}' не найден")


class InvalidPasswordError(ValutaTradeError):
    """Неверный пароль."""

    def __init__(self) -> None:
        super().__init__("Неверный пароль")


class AuthRequiredError(ValutaTradeError):
    """Команда доступна только залогиненному пользователю."""

    def __init__(self) -> None:
        super().__init__("Сначала выполните login")


class WalletNotFoundError(ValutaTradeError):
    """У пользователя нет кошелька в указанной валюте."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"У вас нет кошелька '{code}'. Добавьте валюту: "
            "она создаётся автоматически при первой покупке."
        )


class RatesCacheEmptyError(ValutaTradeError):
    """Локальный кеш курсов пуст или отсутствует."""

    def __init__(self) -> None:
        super().__init__(
            "Локальный кеш курсов пуст. "
            "Выполните 'update-rates', чтобы загрузить данные."
        )


class RateNotInCacheError(ValutaTradeError):
    """Курс для указанной валюты отсутствует в кеше."""

    def __init__(self, code: str) -> None:
        super().__init__(f"Курс для '{code}' не найден в кеше.")


class StorageError(ValutaTradeError):
    """Ошибка чтения/записи JSON-хранилища."""
