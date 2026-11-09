"""Клиенты внешних API курсов с единым интерфейсом ``fetch_rates()``.

Все клиенты возвращают курсы в стандартизированном виде
``{"BTC_USD": 59337.21, ...}``, где значение — сколько единиц второй валюты
стоит одна единица первой. Любые сбои превращаются в ApiRequestError.
"""

import math
import time
from abc import ABC, abstractmethod
from typing import Any

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.parser_service.config import ParserConfig

HTTP_OK = 200
HTTP_SERVER_ERROR = 500

_STATUS_MESSAGES = {
    400: "некорректный запрос (400)",
    401: "неверный или отсутствующий API-ключ (401 Unauthorized)",
    403: "доступ запрещён — проверьте API-ключ (403 Forbidden)",
    404: "ресурс не найден (404)",
    429: "превышен лимит запросов (429 Too Many Requests), повторите позже",
}


def _is_valid_rate(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


class BaseApiClient(ABC):
    """Базовый клиент: HTTP-запрос, замер времени, обработка ошибок."""

    source_name: str = "API"

    def __init__(self, config: ParserConfig | None = None) -> None:
        self.config = config or ParserConfig()
        self.last_meta: dict[str, Any] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получить курсы в формате ``{"FROM_TO": rate}``."""

    def _describe_error(self, status_code: int, body: Any) -> str:
        """Человекочитаемое описание HTTP-ошибки (может переопределяться)."""
        if status_code in _STATUS_MESSAGES:
            return _STATUS_MESSAGES[status_code]
        if status_code >= HTTP_SERVER_ERROR:
            return f"сервис временно недоступен ({status_code})"
        return f"неожиданный ответ сервера ({status_code})"

    def _get_json(self, url: str, params: dict[str, str] | None = None) -> Any:
        timeout = self.config.REQUEST_TIMEOUT
        started = time.perf_counter()
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except requests.exceptions.Timeout:
            raise ApiRequestError(
                f"{self.source_name}: превышено время ожидания ({timeout} с)"
            ) from None
        except requests.exceptions.ConnectionError:
            raise ApiRequestError(
                f"{self.source_name}: сетевая ошибка — нет соединения с сервером"
            ) from None
        except requests.exceptions.RequestException as error:
            raise ApiRequestError(f"{self.source_name}: {error}") from None

        self.last_meta = {
            "request_ms": round((time.perf_counter() - started) * 1000),
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }
        try:
            body = response.json()
        except ValueError:
            body = None

        if response.status_code != HTTP_OK:
            reason = self._describe_error(response.status_code, body)
            raise ApiRequestError(f"{self.source_name}: {reason}")
        if body is None:
            raise ApiRequestError(f"{self.source_name}: ответ не является JSON")
        return body


class CoinGeckoClient(BaseApiClient):
    """Курсы криптовалют из CoinGecko (публичный доступ без ключа)."""

    source_name = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        cfg = self.config
        base = cfg.BASE_CURRENCY
        ids = {
            code: cfg.CRYPTO_ID_MAP[code]
            for code in cfg.CRYPTO_CURRENCIES
            if code in cfg.CRYPTO_ID_MAP
        }
        if not ids:
            raise ApiRequestError(f"{self.source_name}: список криптовалют пуст")

        data = self._get_json(
            cfg.COINGECKO_URL,
            params={"ids": ",".join(ids.values()), "vs_currencies": base.lower()},
        )
        if not isinstance(data, dict):
            raise ApiRequestError(f"{self.source_name}: неожиданный формат ответа")

        rates: dict[str, float] = {}
        raw_ids: dict[str, str] = {}
        for code, raw_id in ids.items():
            value = (data.get(raw_id) or {}).get(base.lower())
            if _is_valid_rate(value):
                pair = f"{code}_{base}"
                rates[pair] = float(value)
                raw_ids[pair] = raw_id
        if not rates:
            raise ApiRequestError(f"{self.source_name}: в ответе нет курсов")
        self.last_meta["raw_ids"] = raw_ids
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Курсы фиатных валют из ExchangeRate-API."""

    source_name = "ExchangeRate-API"

    _ERROR_TYPES = {
        "invalid-key": "неверный API-ключ",
        "inactive-account": "аккаунт не активирован (подтвердите e-mail)",
        "quota-reached": "исчерпан лимит запросов тарифа",
        "unsupported-code": "неподдерживаемый код валюты",
        "malformed-request": "некорректный запрос",
    }

    def _url(self) -> str:
        cfg = self.config
        if not cfg.EXCHANGERATE_API_KEY:
            raise ApiRequestError(f"{self.source_name}: не задан EXCHANGERATE_API_KEY")
        return (
            f"{cfg.EXCHANGERATE_API_URL}/{cfg.EXCHANGERATE_API_KEY}"
            f"/latest/{cfg.BASE_CURRENCY}"
        )

    def _describe_error(self, status_code: int, body: Any) -> str:
        if isinstance(body, dict) and body.get("error-type") in self._ERROR_TYPES:
            return f"{self._ERROR_TYPES[body['error-type']]} ({status_code})"
        return super()._describe_error(status_code, body)

    def fetch_rates(self) -> dict[str, float]:
        cfg = self.config
        base = cfg.BASE_CURRENCY
        data = self._get_json(self._url())
        if not isinstance(data, dict) or data.get("result") != "success":
            error_type = data.get("error-type") if isinstance(data, dict) else None
            reason = self._ERROR_TYPES.get(error_type, error_type or "ошибка API")
            raise ApiRequestError(f"{self.source_name}: {reason}")

        raw_rates = data.get("rates") or data.get("conversion_rates") or {}
        rates: dict[str, float] = {}
        for code in cfg.FIAT_CURRENCIES:
            units_per_base = raw_rates.get(code)
            if _is_valid_rate(units_per_base):
                rates[f"{code}_{base}"] = 1 / float(units_per_base)
        if not rates:
            raise ApiRequestError(f"{self.source_name}: в ответе нет курсов")
        return rates
