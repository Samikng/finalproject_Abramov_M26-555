"""RatesUpdater — координация обновления курсов из всех источников."""

import logging
from dataclasses import dataclass, field
from typing import Any

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import utc_now_iso
from valutatrade_hub.logging_config import PARSER_LOGGER
from valutatrade_hub.parser_service.api_clients import (
    BaseApiClient,
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage

SOURCES: dict[str, type[BaseApiClient]] = {
    "coingecko": CoinGeckoClient,
    "exchangerate": ExchangeRateApiClient,
}


@dataclass
class UpdateResult:
    """Итог одного запуска обновления."""

    total_rates: int = 0
    last_refresh: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class RatesUpdater:
    """Опрашивает клиентов, объединяет курсы и передаёт их в хранилище."""

    def __init__(
        self,
        clients: list[BaseApiClient],
        storage: RatesStorage,
        logger: logging.Logger | None = None,
    ) -> None:
        self.clients = clients
        self.storage = storage
        self.logger = logger or logging.getLogger(PARSER_LOGGER)

    def run_update(self) -> UpdateResult:
        """Выполнить обновление.

        Отказоустойчивость: ошибка одного клиента логируется, остальные
        продолжают работу. ApiRequestError бросается, только если не удалось
        получить ни одного курса.
        """
        log = self.logger
        log.info("Starting rates update...")
        result = UpdateResult()
        pairs: dict[str, dict[str, Any]] = {}
        history: list[dict[str, Any]] = []

        for client in self.clients:
            name = client.source_name
            try:
                rates = client.fetch_rates()
            except ApiRequestError as error:
                reason = error.reason.removeprefix(f"{name}: ")
                log.error(f"Failed to fetch from {name}: {reason}")
                result.errors.append(f"{name}: {reason}")
                continue
            log.info(f"Fetching from {name}... OK ({len(rates)} rates)")
            timestamp = utc_now_iso()
            for pair, rate in rates.items():
                pairs[pair] = {"rate": rate, "updated_at": timestamp, "source": name}
                history.append(self._history_record(client, pair, rate, timestamp))

        if not pairs:
            log.error("Rates update failed: no data from any source.")
            raise ApiRequestError("не удалось получить курсы ни из одного источника")

        result.last_refresh = utc_now_iso()
        log.info(f"Writing {len(pairs)} rates to {self.storage.rates_path.name}...")
        self.storage.save_snapshot(pairs, result.last_refresh)
        added = self.storage.append_history(history)
        log.debug(f"History: {added} new records in {self.storage.history_path.name}")
        result.total_rates = len(pairs)
        log.info(
            f"Update finished: {result.total_rates} rates, "
            f"{len(result.errors)} source errors."
        )
        return result

    @staticmethod
    def _history_record(
        client: BaseApiClient, pair: str, rate: float, timestamp: str
    ) -> dict[str, Any]:
        from_code, to_code = pair.split("_", 1)
        meta = {
            key: client.last_meta.get(key)
            for key in ("request_ms", "status_code", "etag")
        }
        raw_id = client.last_meta.get("raw_ids", {}).get(pair)
        if raw_id:
            meta = {"raw_id": raw_id, **meta}
        return {
            "id": f"{pair}_{timestamp}",
            "from_currency": from_code,
            "to_currency": to_code,
            "rate": rate,
            "timestamp": timestamp,
            "source": client.source_name,
            "meta": meta,
        }


def build_updater(
    source: str | None = None, config: ParserConfig | None = None
) -> RatesUpdater:
    """Собрать RatesUpdater для всех источников или для одного (``source``).

    Raises:
        ValueError: неизвестное имя источника.
    """
    config = config or ParserConfig()
    if source is None:
        client_types = list(SOURCES.values())
    else:
        key = source.strip().lower()
        if key not in SOURCES:
            known = ", ".join(SOURCES)
            raise ValueError(f"Неизвестный источник '{source}'. Доступны: {known}")
        client_types = [SOURCES[key]]
    clients = [client_type(config) for client_type in client_types]
    storage = RatesStorage(config.RATES_FILE_PATH, config.HISTORY_FILE_PATH)
    return RatesUpdater(clients, storage)
