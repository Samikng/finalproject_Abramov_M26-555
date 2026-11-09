"""DatabaseManager — абстракция над JSON-хранилищем (Singleton)."""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader


def read_json(path: Path, default: Any) -> Any:
    """Прочитать JSON; для отсутствующего или пустого файла вернуть ``default``."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except OSError as error:
        raise StorageError(f"Не удалось прочитать {path}: {error}") from error
    if not text.strip():
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise StorageError(f"Файл {path} повреждён: {error}") from error


def atomic_write_json(path: Path, data: Any) -> None:
    """Атомарная запись: сначала во временный файл, затем ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except OSError as error:
        tmp_path.unlink(missing_ok=True)
        raise StorageError(f"Не удалось записать {path}: {error}") from error


class DatabaseManager:
    """Единый доступ к коллекциям users / portfolios / rates.

    Singleton через ``__new__`` (по той же причине, что и SettingsLoader).
    Пути к файлам берутся из SettingsLoader.
    """

    _instance: "DatabaseManager | None" = None

    _COLLECTIONS: dict[str, tuple[str, Any]] = {
        "users": ("users_file", list),
        "portfolios": ("portfolios_file", list),
        "rates": ("rates_file", dict),
    }

    def __new__(cls) -> "DatabaseManager":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._settings = SettingsLoader()
            cls._instance = instance
        return cls._instance

    def path(self, collection: str) -> Path:
        """Путь к файлу коллекции."""
        file_key, _ = self._spec(collection)
        return self._settings.data_path(file_key)

    def read(self, collection: str) -> Any:
        """Прочитать коллекцию целиком."""
        _, factory = self._spec(collection)
        return read_json(self.path(collection), factory())

    def write(self, collection: str, data: Any) -> None:
        """Атомарно перезаписать коллекцию."""
        atomic_write_json(self.path(collection), data)

    @contextmanager
    def transaction(self, collection: str) -> Iterator[Any]:
        """Безопасная операция «чтение → модификация → запись».

        Данные записываются только если блок ``with`` завершился без исключения,
        поэтому при ошибке файл остаётся в исходном состоянии.
        """
        data = self.read(collection)
        yield data
        self.write(collection, data)

    def _spec(self, collection: str) -> tuple[str, Any]:
        try:
            return self._COLLECTIONS[collection]
        except KeyError:
            raise StorageError(f"Неизвестная коллекция '{collection}'") from None
