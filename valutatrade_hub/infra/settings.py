"""SettingsLoader — единая точка конфигурации приложения (Singleton).

Источник: секция ``[tool.valutatrade]`` файла pyproject.toml в корне проекта
(корень ищется вверх от текущего каталога). Отсутствующие ключи берутся из
значений по умолчанию.

Ключи конфигурации:
    data_dir               — каталог с JSON-файлами (относительно корня проекта);
    users_file, portfolios_file, rates_file, history_file — имена файлов в data_dir;
    rates_ttl_seconds      — сколько секунд курс в rates.json считается свежим;
    refresh_retry_seconds  — пауза перед повторной автопопыткой обновить курсы;
    default_base_currency  — базовая валюта по умолчанию (USD);
    log_dir, log_level, log_format, log_date_format,
    log_max_bytes, log_backup_count — параметры логирования и ротации.
"""

import tomllib
from pathlib import Path
from typing import Any

_MISSING = object()

DEFAULTS: dict[str, Any] = {
    "data_dir": "data",
    "users_file": "users.json",
    "portfolios_file": "portfolios.json",
    "rates_file": "rates.json",
    "history_file": "exchange_rates.json",
    "rates_ttl_seconds": 300,
    "refresh_retry_seconds": 60,
    "default_base_currency": "USD",
    "log_dir": "logs",
    "log_level": "INFO",
    "log_format": "%(levelname)s %(asctime)s %(message)s",
    "log_date_format": "%Y-%m-%dT%H:%M:%S",
    "log_max_bytes": 1_048_576,
    "log_backup_count": 5,
}


def _find_project_root(start: Path) -> Path:
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file():
            return directory
    return start


class SettingsLoader:
    """Загрузка и кеширование конфигурации; в приложении ровно один экземпляр.

    Singleton реализован через ``__new__``: это самый короткий и читаемый
    способ — не нужен отдельный метакласс, а логика «создать один раз» видна
    прямо в классе. Повторные ``SettingsLoader()`` (в т.ч. при импортах из
    разных модулей) возвращают тот же объект, конфигурация читается один раз.
    """

    _instance: "SettingsLoader | None" = None

    def __new__(cls) -> "SettingsLoader":
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._config = {}
            instance._root = Path.cwd()
            instance._load()
            cls._instance = instance
        return cls._instance

    def _load(self) -> None:
        self._root = _find_project_root(Path.cwd())
        config = dict(DEFAULTS)
        pyproject = self._root / "pyproject.toml"
        if pyproject.is_file():
            with pyproject.open("rb") as file:
                section = tomllib.load(file).get("tool", {}).get("valutatrade", {})
            config.update(section)
        self._config = config

    def get(self, key: str, default: Any = _MISSING) -> Any:
        """Значение настройки; KeyError, если ключа нет и default не задан."""
        if key in self._config:
            return self._config[key]
        if default is _MISSING:
            raise KeyError(f"Неизвестный ключ конфигурации: {key}")
        return default

    def reload(self) -> None:
        """Перечитать конфигурацию с диска."""
        self._load()

    @property
    def project_root(self) -> Path:
        """Корневой каталог проекта (где лежит pyproject.toml)."""
        return self._root

    def resolve(self, relative: str) -> Path:
        """Путь относительно корня проекта."""
        path = Path(relative)
        return path if path.is_absolute() else self._root / path

    @property
    def data_dir(self) -> Path:
        return self.resolve(self.get("data_dir"))

    @property
    def log_dir(self) -> Path:
        return self.resolve(self.get("log_dir"))

    def data_path(self, file_key: str) -> Path:
        """Полный путь к файлу данных по ключу (например, ``"rates_file"``)."""
        return self.data_dir / self.get(file_key)
