# ValutaTrade Hub

Консольное приложение — платформа для отслеживания и симуляции торговли фиатными
и криптовалютами. Пользователь регистрируется, ведёт виртуальный портфель
(кошельки в разных валютах), покупает и продаёт валюту по актуальным курсам.

Система состоит из двух частей:

- **Core Service** — CLI, пользователи, портфели, сделки, работа с кешем курсов;
- **Parser Service** — получение курсов из CoinGecko (крипто) и ExchangeRate-API
  (фиат), запись снимка в `data/rates.json` и истории в `data/exchange_rates.json`.

## Структура проекта

```
finalproject_Abramov_M26-555/
├── data/
│   ├── users.json            # пользователи (соль + SHA-256 хеш пароля)
│   ├── portfolios.json       # портфели и кошельки
│   ├── rates.json            # локальный кеш курсов для Core Service
│   └── exchange_rates.json   # история измерений Parser Service
├── valutatrade_hub/
│   ├── logging_config.py     # формат логов, ротация
│   ├── decorators.py         # @log_action
│   ├── core/
│   │   ├── currencies.py     # Currency (ABC), FiatCurrency, CryptoCurrency, get_currency()
│   │   ├── exceptions.py     # доменные исключения
│   │   ├── models.py         # User, Wallet, Portfolio
│   │   ├── usecases.py       # бизнес-логика
│   │   └── utils.py          # валидация, форматирование, кеш-замыкание
│   ├── infra/
│   │   ├── settings.py       # SettingsLoader (Singleton)
│   │   └── database.py       # DatabaseManager (Singleton), атомарная запись JSON
│   ├── parser_service/
│   │   ├── config.py         # ParserConfig: API, валюты, пути, таймауты
│   │   ├── api_clients.py    # BaseApiClient, CoinGeckoClient, ExchangeRateApiClient
│   │   ├── updater.py        # RatesUpdater
│   │   ├── storage.py        # RatesStorage: rates.json + exchange_rates.json
│   │   └── scheduler.py      # периодическое обновление
│   └── cli/
│       └── interface.py      # команды CLI
├── main.py
├── Makefile
├── pyproject.toml
└── uv.lock
```

## Установка и запуск

Нужны Python 3.12+ и [uv](https://docs.astral.sh/uv/).

```bash
make install        # uv sync — зависимости (prettytable, requests, ruff)
make project        # uv run project — запуск CLI
make lint           # uv run ruff check .
make build          # uv build — сборка пакета в dist/
make package-install  # uv tool install dist/*.whl
```

Без `make` (например, на Windows): `uv sync`, затем `uv run project`
(или `uv run python main.py`). Запускайте из корня проекта — оттуда
читаются `pyproject.toml` и каталог `data/`.

## Команды CLI

После запуска открывается интерактивная оболочка (`help` — список команд,
`help <команда>` — справка, `exit` — выход).

| Команда | Назначение |
|---|---|
| `register --username <str> --password <str>` | регистрация (пароль ≥ 4 символов) |
| `login --username <str> --password <str>` | вход |
| `show-portfolio [--base <код>]` | кошельки и итог в базовой валюте (USD по умолчанию) |
| `buy --currency <код> --amount <float>` | покупка (оплата с USD-кошелька) |
| `sell --currency <код> --amount <float>` | продажа (выручка на USD-кошелёк) |
| `get-rate --from <код> --to <код>` | курс и обратный курс |
| `update-rates [--source coingecko\|exchangerate]` | обновить курсы через Parser Service |
| `show-rates [--currency <код>] [--top <N>] [--base <код>]` | курсы из кеша |

Логика сделок: покупка не-USD валюты списывает `amount × курс` с USD-кошелька,
продажа начисляет выручку на USD-кошелёк. Покупка самой USD — пополнение счёта,
поэтому новый пользователь начинает с `buy --currency USD --amount 5000`.
Кошелёк покупаемой валюты создаётся автоматически.

### Пример сессии

```
> register --username alice --password 1234
Пользователь 'alice' зарегистрирован (id=1). Войдите: login --username alice --password ****
> login --username alice --password 1234
Вы вошли как 'alice'
> buy --currency USD --amount 5000
Покупка выполнена: 5000.00 USD
Изменения в портфеле:
- USD: было 0.00 → стало 5000.00
> buy --currency BTC --amount 0.05
Покупка выполнена: 0.0500 BTC по курсу 74872.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0000 → стало 0.0500
- USD: было 5000.00 → стало 1256.40
Оценочная стоимость покупки: 3,743.60 USD
> sell --currency BTC --amount 0.01
Продажа выполнена: 0.0100 BTC по курсу 74872.00 USD/BTC
Изменения в портфеле:
- BTC: было 0.0500 → стало 0.0400
- USD: было 1256.40 → стало 2005.12
Оценочная выручка: 748.72 USD
> show-portfolio
Портфель пользователя 'alice' (база: USD):
+--------+---------+----------------+
| Валюта |  Баланс | Стоимость, USD |
+--------+---------+----------------+
|    BTC |  0.0400 |       2,994.88 |
|    USD | 2005.12 |       2,005.12 |
+--------+---------+----------------+
ИТОГО: 5,000.00 USD
> get-rate --from USD --to BTC
Курс USD→BTC: 0.00001336 (обновлено: 2026-11-09 16:51:54)
Обратный курс BTC→USD: 74872.00
> sell --currency BTC --amount 1
Недостаточно средств: доступно 0.0400 BTC, требуется 1.0000 BTC
> get-rate --from USD --to ABC
Неизвестная валюта 'ABC'
Поддерживаемые валюты: BTC, ETH, EUR, GBP, RUB, SOL, USD
Подробнее: help get-rate
> update-rates
INFO: Starting rates update...
INFO: Fetching from CoinGecko... OK (3 rates)
INFO: Fetching from ExchangeRate-API... OK (3 rates)
INFO: Writing 6 rates to rates.json...
INFO: Update finished: 6 rates, 0 source errors.
Update successful. Total rates updated: 6. Last refresh: 2026-11-09T16:51:54Z
> show-rates --top 2
Rates from cache (updated at 2026-11-09T16:51:54Z):
+---------+----------+---------------------+-----------+
| Пара    |     Курс | Обновлено           | Источник  |
+---------+----------+---------------------+-----------+
| BTC_USD | 74872.00 | 2026-11-09 16:51:54 | CoinGecko |
| ETH_USD |  2129.26 | 2026-11-09 16:51:54 | CoinGecko |
+---------+----------+---------------------+-----------+
```

## Кеш курсов и TTL

- `data/rates.json` хранит по одному последнему срезу на пару `X_USD`
  (`rate` — сколько USD стоит 1 X), а также `updated_at`, `source` и `last_refresh`.
  Кросс-курсы (например, EUR→RUB) считаются через USD.
- Курс считается свежим `rates_ttl_seconds` секунд (по умолчанию 300).
  Если курс устарел или отсутствует, `get-rate`, `buy`, `sell` и
  `show-portfolio` сами вызывают Parser Service. Если обновить не удалось,
  используется последний известный курс с предупреждением; если курса нет
  совсем — `Курс X→Y недоступен. Повторите попытку позже.`
- Новый срез пары заменяет старый, только если его `updated_at` не старше.
- `data/exchange_rates.json` — журнал всех измерений с уникальным
  `id = <FROM>_<TO>_<ISO-UTC>` и метаданными запроса (`request_ms`,
  `status_code`, `etag`, `raw_id`).
- Все записи JSON атомарные: временный файл, затем `os.replace`.

## Parser Service и API-ключ

- **CoinGecko** — публичный доступ, ключ не нужен.
- **ExchangeRate-API** — зарегистрируйтесь на https://www.exchangerate-api.com/
  и передайте ключ через переменную окружения:

  ```bash
  export EXCHANGERATE_API_KEY=ваш_ключ        # bash
  $env:EXCHANGERATE_API_KEY="ваш_ключ"        # PowerShell
  ```

  или создайте в корне проекта файл `.env` (он в `.gitignore`):

  ```
  EXCHANGERATE_API_KEY=ваш_ключ
  ```

  Без ключа ExchangeRate-API не опрашивается (ошибка пишется в лог), курсы
  криптовалют из CoinGecko при этом обновляются.

Ручное обновление: `update-rates` в CLI. Периодическое обновление:

```bash
uv run python -m valutatrade_hub.parser_service.scheduler --interval 300
```

Ошибки API (таймаут, нет сети, 401/403 — неверный ключ, 429 — лимит запросов,
5xx) превращаются в `ApiRequestError`. Сбой одного источника не мешает другому.

## Конфигурация

Секция `[tool.valutatrade]` в `pyproject.toml` (читает `SettingsLoader`):
пути к данным (`data_dir`, `users_file`, …), `rates_ttl_seconds`,
`default_base_currency`, а также параметры логов
`log_dir`, `log_level`, `log_format`, `log_max_bytes`, `log_backup_count`.
Параметры API и списки валют задаются в `valutatrade_hub/parser_service/config.py`.

## Логирование

Строковый формат, ротация по размеру (1 МБ × 5 файлов), каталог `logs/`:

- `actions.log` — операции REGISTER / LOGIN / BUY / SELL (`@log_action`):
  ```
  INFO 2026-11-09T19:51:54 BUY user='alice' currency='BTC' amount=0.0500 rate=74872.00 base='USD' changes=[BTC:0.0000->0.0500,USD:5000.0000->1256.4000] result=OK
  ```
- `parser.log` — шаги Parser Service.

## Демо

Запись asciinema/GIF: _добавьте ссылку_.
