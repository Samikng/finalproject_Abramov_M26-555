"""Декоратор @log_action — прозрачное логирование доменных операций.

Поля записи: timestamp (ISO, из форматтера), action, user, currency, amount,
rate, base, result=OK|ERROR, error_type/error_message, duration_ms.
При ``verbose=True`` добавляется состояние кошельков «было→стало».

Декоратор не глотает исключения: фиксирует их в логе и пробрасывает дальше.
Пароли и другие аргументы, кроме перечисленных, в лог не попадают.
"""

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar

from valutatrade_hub.logging_config import ACTIONS_LOGGER

P = ParamSpec("P")
R = TypeVar("R")

logger = logging.getLogger(ACTIONS_LOGGER)


def _resolve_username(arguments: dict[str, Any], result: Any) -> str | None:
    if isinstance(result, dict) and result.get("username"):
        return result["username"]
    if arguments.get("username"):
        return str(arguments["username"])
    user_id = arguments.get("user_id")
    if user_id is None:
        return None
    # Ленивый импорт, чтобы decorators не зависел от инфраструктуры при импорте.
    from valutatrade_hub.infra.database import DatabaseManager

    try:
        for record in DatabaseManager().read("users"):
            if record.get("user_id") == user_id:
                return record.get("username")
    except Exception:  # noqa: BLE001 — логирование не должно ломать операцию
        pass
    return f"id={user_id}"


def _format_number(value: Any, digits: int) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return repr(value)


def _build_message(
    action: str,
    arguments: dict[str, Any],
    result: Any,
    verbose: bool,
) -> list[str]:
    info = result if isinstance(result, dict) else {}
    parts = [action, f"user='{_resolve_username(arguments, result)}'"]
    currency = info.get("currency_code", arguments.get("currency_code"))
    if currency:
        parts.append(f"currency='{str(currency).upper()}'")
    amount = info.get("amount", arguments.get("amount"))
    if amount is not None:
        parts.append(f"amount={_format_number(amount, 4)}")
    if info.get("rate") is not None:
        parts.append(f"rate={_format_number(info['rate'], 2)}")
    if info.get("base"):
        parts.append(f"base='{info['base']}'")
    if verbose and info.get("changes"):
        changes = ",".join(
            f"{c['currency_code']}:{c['before']:.4f}->{c['after']:.4f}"
            for c in info["changes"]
        )
        parts.append(f"changes=[{changes}]")
    return parts


def log_action(
    action: str, verbose: bool = False
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Логировать вызов usecase на уровне INFO (ошибки — на уровне ERROR).

    Args:
        action: имя операции (BUY / SELL / REGISTER / LOGIN).
        verbose: добавлять в запись изменения кошельков (ключ ``changes``
            в словаре-результате usecase).
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            bound = signature.bind_partial(*args, **kwargs)
            arguments = dict(bound.arguments)
            started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as error:
                elapsed = (time.perf_counter() - started) * 1000
                parts = _build_message(action, arguments, None, verbose)
                parts += [
                    "result=ERROR",
                    f"error_type={type(error).__name__}",
                    f"error_message='{error}'",
                    f"duration_ms={elapsed:.1f}",
                ]
                logger.error(" ".join(parts))
                raise
            elapsed = (time.perf_counter() - started) * 1000
            parts = _build_message(action, arguments, result, verbose)
            parts += ["result=OK", f"duration_ms={elapsed:.1f}"]
            logger.info(" ".join(parts))
            return result

        return wrapper

    return decorator
