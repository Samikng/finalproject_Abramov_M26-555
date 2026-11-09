"""Хранилище Parser Service: снимок rates.json и история exchange_rates.json."""

from pathlib import Path
from typing import Any

from valutatrade_hub.core.utils import parse_iso
from valutatrade_hub.infra.database import atomic_write_json, read_json

SNAPSHOT_SOURCE = "ParserService"


class RatesStorage:
    """Чтение/запись курсов с атомарной записью (tmp → rename)."""

    def __init__(self, rates_path: Path, history_path: Path) -> None:
        self.rates_path = Path(rates_path)
        self.history_path = Path(history_path)

    # --- rates.json: последний срез по каждой паре ---

    def load_snapshot(self) -> dict[str, Any]:
        data = read_json(self.rates_path, {})
        if not isinstance(data, dict):
            data = {}
        data.setdefault("pairs", {})
        return data

    def save_snapshot(self, pairs: dict[str, dict[str, Any]], last_refresh: str) -> int:
        """Слить новые курсы в rates.json и вернуть число обновлённых пар.

        Для каждой пары хранится только один срез; новое значение «побеждает»,
        если его ``updated_at`` не старше текущего.
        """
        snapshot = self.load_snapshot()
        current = snapshot["pairs"]
        updated = 0
        for pair, entry in pairs.items():
            existing = current.get(pair)
            if existing is None or _is_newer(entry, existing):
                current[pair] = entry
                updated += 1
        snapshot["source"] = SNAPSHOT_SOURCE
        snapshot["last_refresh"] = last_refresh
        atomic_write_json(self.rates_path, snapshot)
        return updated

    # --- exchange_rates.json: журнал всех измерений ---

    def load_history(self) -> list[dict[str, Any]]:
        data = read_json(self.history_path, [])
        return data if isinstance(data, list) else []

    def append_history(self, records: list[dict[str, Any]]) -> int:
        """Добавить записи истории без дублей по ``id``; вернуть число новых."""
        history = self.load_history()
        known_ids = {record.get("id") for record in history}
        fresh = [record for record in records if record["id"] not in known_ids]
        if fresh:
            history.extend(fresh)
            atomic_write_json(self.history_path, history)
        return len(fresh)


def _is_newer(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    try:
        return parse_iso(candidate["updated_at"]) >= parse_iso(existing["updated_at"])
    except (KeyError, TypeError, ValueError):
        return True
