"""Бизнес-логика Core Service.

CLI вызывает только функции этого модуля. Здесь используются синглтоны:
    SettingsLoader  — TTL курсов, базовая валюта, пути;
    DatabaseManager — безопасные операции «чтение → модификация → запись».
Операции register/login/buy/sell логируются декоратором @log_action.
"""

import logging
import time
from typing import Any

from valutatrade_hub.core.currencies import get_currency, is_crypto_code
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    InvalidPasswordError,
    RateNotInCacheError,
    RatesCacheEmptyError,
    RateUnavailableError,
    UnknownBaseCurrencyError,
    UserAlreadyExistsError,
    UserNotFoundError,
    WalletNotFoundError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import (
    age_seconds,
    make_mtime_cache,
    normalize_currency_code,
    validate_amount,
)
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager, read_json
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import APP_LOGGER
from valutatrade_hub.parser_service.updater import UpdateResult, build_updater

logger = logging.getLogger(APP_LOGGER)

settings = SettingsLoader()
db = DatabaseManager()

# Курсы во всех парах хранятся относительно этой валюты (X_USD).
PIVOT_CURRENCY = "USD"

# Кеш чтения rates.json (замыкание, сбрасывается при изменении файла).
_read_rates_file = make_mtime_cache(lambda path: read_json(path, {}))


# --- Пользователи ------------------------------------------------------------


def _find_user_record(users: list[dict], username: str) -> dict | None:
    return next((u for u in users if u.get("username") == username), None)


def _load_user(user_id: int) -> User:
    for record in db.read("users"):
        if record.get("user_id") == user_id:
            return User.from_dict(record)
    raise UserNotFoundError(f"id={user_id}")


@log_action("REGISTER")
def register_user(username: str, password: str) -> dict[str, Any]:
    """Зарегистрировать пользователя и создать ему пустой портфель."""
    username = (username or "").strip()
    if not username:
        raise ValueError("Имя пользователя не может быть пустым")
    with db.transaction("users") as users:
        if _find_user_record(users, username) is not None:
            raise UserAlreadyExistsError(username)
        user_id = max((u.get("user_id", 0) for u in users), default=0) + 1
        user = User.create(user_id, username, password)
        users.append(user.to_dict())
    with db.transaction("portfolios") as portfolios:
        if not any(p.get("user_id") == user_id for p in portfolios):
            portfolios.append(Portfolio(user_id).to_dict())
    return {"user_id": user.user_id, "username": user.username}


@log_action("LOGIN")
def login_user(username: str, password: str) -> dict[str, Any]:
    """Проверить логин/пароль и вернуть данные пользователя для сессии."""
    username = (username or "").strip()
    record = _find_user_record(db.read("users"), username)
    if record is None:
        raise UserNotFoundError(username)
    user = User.from_dict(record)
    if not user.verify_password(password):
        raise InvalidPasswordError()
    return {"user_id": user.user_id, "username": user.username}


# --- Курсы -------------------------------------------------------------------


def _load_pairs() -> tuple[dict[str, dict], str | None]:
    """Пары из rates.json (поддерживается и плоский формат из ранних версий)."""
    data = _read_rates_file(db.path("rates"))
    if not isinstance(data, dict):
        return {}, None
    pairs = data.get("pairs")
    if not isinstance(pairs, dict):
        pairs = {k: v for k, v in data.items() if isinstance(v, dict) and "rate" in v}
    return pairs, data.get("last_refresh")


def _rate_to_pivot(code: str, pairs: dict[str, dict]) -> tuple[float, str] | None:
    """Курс ``code → USD`` и время его обновления, либо None."""
    direct = pairs.get(f"{code}_{PIVOT_CURRENCY}")
    if direct and direct.get("rate"):
        return float(direct["rate"]), direct.get("updated_at", "")
    inverse = pairs.get(f"{PIVOT_CURRENCY}_{code}")
    if inverse and inverse.get("rate"):
        return 1 / float(inverse["rate"]), inverse.get("updated_at", "")
    return None


def _compute_rate(
    from_code: str, to_code: str, pairs: dict[str, dict]
) -> tuple[float, str | None] | None:
    """Кросс-курс через USD. updated_at — время более старой из двух пар."""
    legs = []
    for code in (from_code, to_code):
        if code == PIVOT_CURRENCY:
            legs.append((1.0, None))
            continue
        leg = _rate_to_pivot(code, pairs)
        if leg is None:
            return None
        legs.append(leg)
    (from_usd, from_ts), (to_usd, to_ts) = legs
    stamps = [ts for ts in (from_ts, to_ts) if ts is not None]
    updated_at = min(stamps) if stamps else None
    return from_usd / to_usd, updated_at


def _is_fresh(updated_at: str | None) -> bool:
    if updated_at is None:  # USD→USD
        return True
    try:
        return age_seconds(updated_at) <= float(settings.get("rates_ttl_seconds"))
    except ValueError:
        return False


def _make_refresher():
    """Замыкание: автообновление курсов не чаще, чем раз в refresh_retry_seconds.

    Защищает от серии сетевых таймаутов, когда за одну команду нужно
    несколько курсов, а Parser Service недоступен.
    """
    last_attempt: float | None = None

    def refresh() -> bool:
        nonlocal last_attempt
        retry = float(settings.get("refresh_retry_seconds"))
        now = time.monotonic()
        if last_attempt is not None and now - last_attempt < retry:
            return False
        last_attempt = now
        try:
            build_updater().run_update()
        except ApiRequestError as error:
            logger.warning(f"Auto refresh failed: {error}")
            return False
        _read_rates_file.invalidate()
        return True

    return refresh


_refresh_rates = _make_refresher()


def get_rate(from_code: str, to_code: str) -> dict[str, Any]:
    """Текущий курс ``from_code → to_code``.

    Берёт курс из кеша rates.json. Если курса нет или он старше TTL
    (SettingsLoader: rates_ttl_seconds), пытается обновить кеш через
    Parser Service. Если обновить не удалось, а устаревший курс есть —
    возвращает его с флагом ``is_stale``.

    Raises:
        CurrencyNotFoundError: неизвестный код валюты.
        RateUnavailableError: курса нет и Parser Service недоступен.
    """
    src = get_currency(normalize_currency_code(from_code)).code
    dst = get_currency(normalize_currency_code(to_code)).code
    if src == dst:
        return _rate_result(src, dst, 1.0, None, False)

    pairs, _ = _load_pairs()
    found = _compute_rate(src, dst, pairs)
    if (found is None or not _is_fresh(found[1])) and _refresh_rates():
        pairs, _ = _load_pairs()
        found = _compute_rate(src, dst, pairs) or found
    if found is None:
        raise RateUnavailableError(src, dst)
    rate, updated_at = found
    return _rate_result(src, dst, rate, updated_at, not _is_fresh(updated_at))


def _rate_result(
    src: str, dst: str, rate: float, updated_at: str | None, stale: bool
) -> dict[str, Any]:
    return {
        "from": src,
        "to": dst,
        "rate": rate,
        "reverse_rate": 1 / rate,
        "updated_at": updated_at,
        "is_stale": stale,
        "ttl_seconds": settings.get("rates_ttl_seconds"),
    }


def _trade_rate(code: str, base: str) -> dict[str, Any] | None:
    """Курс для сделки; None для операций в самой базовой валюте."""
    if code == base:
        return None
    try:
        return get_rate(code, base)
    except RateUnavailableError:
        raise RateUnavailableError(
            code, base, message=f"Не удалось получить курс для {code}→{base}"
        ) from None


# --- Портфель и сделки -------------------------------------------------------


def _portfolio_record(portfolios: list[dict], user_id: int) -> dict:
    record = next((p for p in portfolios if p.get("user_id") == user_id), None)
    if record is None:
        record = Portfolio(user_id).to_dict()
        portfolios.append(record)
    return record


def _trade_base() -> str:
    return str(settings.get("default_base_currency")).upper()


@log_action("BUY", verbose=True)
def buy(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Купить ``amount`` единиц валюты.

    Покупка не-USD валюты оплачивается с USD-кошелька по текущему курсу.
    Покупка самой USD — пополнение USD-кошелька.
    Кошелёк покупаемой валюты создаётся автоматически.
    """
    amount = validate_amount(amount)
    code = get_currency(normalize_currency_code(currency_code)).code
    base = _trade_base()
    user = _load_user(user_id)
    rate_info = _trade_rate(code, base)
    cost = amount * rate_info["rate"] if rate_info else amount

    changes = []
    with db.transaction("portfolios") as portfolios:
        record = _portfolio_record(portfolios, user_id)
        portfolio = Portfolio.from_dict(record, user)
        if rate_info is not None:
            pay_wallet = portfolio.get_wallet(base)
            if pay_wallet is None:
                raise InsufficientFundsError(available=0.0, required=cost, code=base)
            before = pay_wallet.balance
            pay_wallet.withdraw(cost)
            changes.append(_change(base, before, pay_wallet.balance))
        wallet = portfolio.get_or_create_wallet(code)
        before = wallet.balance
        wallet.deposit(amount)
        changes.insert(0, _change(code, before, wallet.balance))
        record.update(portfolio.to_dict())

    return _trade_result(user, code, amount, base, rate_info, cost, changes)


@log_action("SELL", verbose=True)
def sell(user_id: int, currency_code: str, amount: float) -> dict[str, Any]:
    """Продать ``amount`` единиц валюты; выручка зачисляется на USD-кошелёк."""
    amount = validate_amount(amount)
    code = get_currency(normalize_currency_code(currency_code)).code
    base = _trade_base()
    user = _load_user(user_id)

    portfolio = Portfolio.from_dict(_portfolio_record(db.read("portfolios"), user_id))
    wallet = portfolio.get_wallet(code)
    if wallet is None:
        raise WalletNotFoundError(code)
    if amount > wallet.balance:
        raise InsufficientFundsError(wallet.balance, amount, code)

    rate_info = _trade_rate(code, base)
    revenue = amount * rate_info["rate"] if rate_info else amount

    changes = []
    with db.transaction("portfolios") as portfolios:
        record = _portfolio_record(portfolios, user_id)
        portfolio = Portfolio.from_dict(record, user)
        wallet = portfolio.get_wallet(code)
        if wallet is None:
            raise WalletNotFoundError(code)
        before = wallet.balance
        wallet.withdraw(amount)
        changes.append(_change(code, before, wallet.balance))
        if rate_info is not None:
            receive_wallet = portfolio.get_or_create_wallet(base)
            before = receive_wallet.balance
            receive_wallet.deposit(revenue)
            changes.append(_change(base, before, receive_wallet.balance))
        record.update(portfolio.to_dict())

    return _trade_result(user, code, amount, base, rate_info, revenue, changes)


def _change(code: str, before: float, after: float) -> dict[str, Any]:
    return {"currency_code": code, "before": before, "after": after}


def _trade_result(
    user: User,
    code: str,
    amount: float,
    base: str,
    rate_info: dict | None,
    value: float,
    changes: list[dict],
) -> dict[str, Any]:
    return {
        "username": user.username,
        "currency_code": code,
        "amount": amount,
        "base": base,
        "rate": rate_info["rate"] if rate_info else None,
        "rate_updated_at": rate_info["updated_at"] if rate_info else None,
        "is_stale": bool(rate_info and rate_info["is_stale"]),
        "value": value,
        "changes": changes,
    }


def get_portfolio_summary(user_id: int, base: str | None = None) -> dict[str, Any]:
    """Кошельки пользователя и их стоимость в базовой валюте.

    Raises:
        UnknownBaseCurrencyError: неизвестная базовая валюта.
    """
    base_code = (base or _trade_base()).strip().upper()
    try:
        base_code = get_currency(base_code).code
    except CurrencyNotFoundError:
        raise UnknownBaseCurrencyError(base_code) from None

    user = _load_user(user_id)
    portfolio = Portfolio.from_dict(
        _portfolio_record(db.read("portfolios"), user_id), user
    )
    rows: list[dict[str, Any]] = []
    known_rates: dict[str, float] = {}
    stale = False
    for code, wallet in sorted(portfolio.wallets.items()):
        value = None
        try:
            info = get_rate(code, base_code)
        except ApiRequestError:
            info = None
        if info is not None:
            known_rates[code] = info["rate"]
            stale = stale or info["is_stale"]
            value = wallet.balance * info["rate"]
        rows.append({"currency_code": code, "balance": wallet.balance, "value": value})

    # Валюты без курса не учитываются в итоге (о них сообщает has_unpriced).
    total = portfolio.get_total_value(
        base_code, rate_provider=lambda src, _dst: known_rates.get(src, 0.0)
    )
    return {
        "username": user.username,
        "base": base_code,
        "rows": rows,
        "total": total,
        "is_stale": stale,
        "has_unpriced": any(r["value"] is None for r in rows),
    }


# --- Parser Service ----------------------------------------------------------


def update_rates(source: str | None = None) -> UpdateResult:
    """Немедленно обновить курсы (все источники или один)."""
    result = build_updater(source).run_update()
    _read_rates_file.invalidate()
    return result


def show_rates(
    currency: str | None = None, top: int | None = None, base: str | None = None
) -> dict[str, Any]:
    """Курсы из локального кеша с фильтрацией.

    Args:
        currency: показать только пары с этой валютой.
        top: N самых дорогих криптовалют.
        base: пересчитать все курсы относительно этой валюты.

    Raises:
        RatesCacheEmptyError: кеш пуст.
        RateNotInCacheError: нет курса для ``currency``.
    """
    pairs, last_refresh = _load_pairs()
    if not pairs:
        raise RatesCacheEmptyError()

    base_code = PIVOT_CURRENCY
    if base:
        base_code = get_currency(normalize_currency_code(base)).code

    rows = _rows_in_base(pairs, base_code)
    if currency:
        code = normalize_currency_code(currency)
        rows = [r for r in rows if r["from"] == code]
        if not rows:
            raise RateNotInCacheError(code)
    if top is not None:
        if top <= 0:
            raise ValueError("'top' должен быть положительным целым числом")
        rows = [r for r in rows if is_crypto_code(r["from"])]
        rows.sort(key=lambda r: r["rate"], reverse=True)
        rows = rows[:top]
    else:
        rows.sort(key=lambda r: r["pair"])
    return {"last_refresh": last_refresh, "base": base_code, "rows": rows}


def _rows_in_base(pairs: dict[str, dict], base_code: str) -> list[dict[str, Any]]:
    """Пересчитать пары X_USD в X_<base>."""
    base_leg = _rate_to_pivot(base_code, pairs) if base_code != PIVOT_CURRENCY else None
    if base_code != PIVOT_CURRENCY and base_leg is None:
        raise RateNotInCacheError(base_code)
    base_rate = base_leg[0] if base_leg else 1.0

    rows = []
    for pair, entry in pairs.items():
        from_code, _, to_code = pair.partition("_")
        if to_code != PIVOT_CURRENCY or from_code == base_code or not entry.get("rate"):
            continue
        rows.append(
            {
                "pair": f"{from_code}_{base_code}",
                "from": from_code,
                "rate": float(entry["rate"]) / base_rate,
                "updated_at": entry.get("updated_at"),
                "source": entry.get("source"),
            }
        )
    if base_code != PIVOT_CURRENCY:
        rows.append(
            {
                "pair": f"{PIVOT_CURRENCY}_{base_code}",
                "from": PIVOT_CURRENCY,
                "rate": 1 / base_rate,
                "updated_at": base_leg[1] if base_leg else None,
                "source": None,
            }
        )
    return rows
