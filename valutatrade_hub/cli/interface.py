"""Командный интерфейс ValutaTrade Hub (интерактивный REPL).

CLI только разбирает аргументы, вызывает функции ``core.usecases`` и
превращает результаты/доменные исключения в сообщения для пользователя.
Строка команды разбирается модулем ``shlex`` (кавычки поддерживаются
одинаково на Windows и Unix, т.к. разбор выполняется самим Python).
"""

import argparse
import logging
import shlex
import sys
from collections.abc import Callable
from typing import Any

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import supported_codes
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    AuthRequiredError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RateUnavailableError,
    UnknownBaseCurrencyError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import (
    format_amount,
    format_money,
    format_rate,
    format_timestamp,
)
from valutatrade_hub.logging_config import ACTIONS_LOGGER, setup_logging
from valutatrade_hub.parser_service.updater import SOURCES

PROMPT = "> "
EXIT_COMMANDS = {"exit"}

logger = logging.getLogger(ACTIONS_LOGGER)


class CliUsageError(Exception):
    """Ошибка разбора аргументов команды."""


class _CommandParser(argparse.ArgumentParser):
    """ArgumentParser, который не завершает процесс при ошибке."""

    def error(self, message: str) -> None:
        raise CliUsageError(f"{message}\nСправка: help {self.prog}")


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("ожидается положительное целое число")
    return number


def _build_parsers() -> dict[str, argparse.ArgumentParser]:
    parsers: dict[str, argparse.ArgumentParser] = {}

    def add(name: str, description: str) -> argparse.ArgumentParser:
        parser = _CommandParser(prog=name, description=description, add_help=True)
        parsers[name] = parser
        return parser

    p = add("register", "Создать нового пользователя.")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)

    p = add("login", "Войти в систему.")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)

    p = add("show-portfolio", "Показать кошельки и итоговую стоимость.")
    p.add_argument("--base", default=None, help="базовая валюта (по умолчанию USD)")

    p = add("buy", "Купить валюту (оплата с USD-кошелька; USD — пополнение).")
    p.add_argument("--currency", required=True, help="код валюты, напр. BTC")
    p.add_argument("--amount", required=True, help="количество в единицах валюты")

    p = add("sell", "Продать валюту (выручка зачисляется на USD-кошелёк).")
    p.add_argument("--currency", required=True)
    p.add_argument("--amount", required=True)

    p = add("get-rate", "Курс одной валюты к другой.")
    p.add_argument("--from", dest="from_code", required=True)
    p.add_argument("--to", dest="to_code", required=True)

    p = add("update-rates", "Немедленно обновить курсы через Parser Service.")
    p.add_argument("--source", choices=sorted(SOURCES), default=None)

    p = add("show-rates", "Курсы из локального кеша.")
    p.add_argument("--currency", default=None)
    p.add_argument("--top", type=_positive_int, default=None)
    p.add_argument("--base", default=None)
    return parsers


class CliApp:
    """Состояние сессии и обработчики команд."""

    def __init__(self) -> None:
        self.parsers = _build_parsers()
        self.current_user: dict[str, Any] | None = None
        self.handlers: dict[str, Callable[[argparse.Namespace], None]] = {
            "register": self.cmd_register,
            "login": self.cmd_login,
            "show-portfolio": self.cmd_show_portfolio,
            "buy": self.cmd_buy,
            "sell": self.cmd_sell,
            "get-rate": self.cmd_get_rate,
            "update-rates": self.cmd_update_rates,
            "show-rates": self.cmd_show_rates,
        }

    def run(self) -> None:
        print("ValutaTrade Hub. Введите 'help' для списка команд, 'exit' для выхода.")
        while True:
            try:
                line = input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.strip().lower() in EXIT_COMMANDS:
                break
            self.execute(line)

    def execute(self, line: str) -> None:
        """Разобрать и выполнить одну строку команды."""
        try:
            tokens = shlex.split(line)
        except ValueError as error:
            print(f"Ошибка разбора команды: {error}")
            return
        if not tokens:
            return
        command, args = tokens[0].lower(), tokens[1:]
        if command == "help":
            self.print_help(args[0] if args else None)
            return
        handler = self.handlers.get(command)
        if handler is None:
            print(f"Неизвестная команда '{command}'. Введите 'help'.")
            return
        try:
            namespace = self.parsers[command].parse_args(args)
        except CliUsageError as error:
            print(f"Ошибка: {error}")
            return
        except SystemExit:
            return
        self._run_handler(command, handler, namespace)

    def _run_handler(
        self,
        command: str,
        handler: Callable[[argparse.Namespace], None],
        namespace: argparse.Namespace,
    ) -> None:
        try:
            handler(namespace)
        except InsufficientFundsError as error:
            print(error)
            if command == "buy" and error.code == "USD":
                print("Пополните USD-кошелёк: buy --currency USD --amount <сумма>")
        except UnknownBaseCurrencyError as error:
            print(error)
            print(f"Поддерживаемые валюты: {', '.join(supported_codes())}")
        except CurrencyNotFoundError as error:
            print(error)
            print(f"Поддерживаемые валюты: {', '.join(supported_codes())}")
            print("Подробнее: help get-rate")
        except RateUnavailableError as error:
            print(error)
        except ApiRequestError as error:
            print(error)
            print("Повторите попытку позже или проверьте подключение к сети.")
        except ValutaTradeError as error:
            print(error)
        except (ValueError, TypeError) as error:
            print(f"Ошибка: {error}")
        except Exception as error:
            logger.exception(f"Unexpected error in '{command}'")
            print(f"Непредвиденная ошибка: {error}")

    def print_help(self, command: str | None) -> None:
        if command and command in self.parsers:
            self.parsers[command].print_help()
            return
        if command:
            print(f"Неизвестная команда '{command}'.")
        print("Команды:")
        for name, parser in self.parsers.items():
            print(f"  {name:<15} {parser.description}")
        print(f"  {'help [команда]':<15} Справка по команде.")
        print(f"  {'exit':<15} Выход.")

    def _require_login(self) -> dict[str, Any]:
        if self.current_user is None:
            raise AuthRequiredError()
        return self.current_user

    def cmd_register(self, args: argparse.Namespace) -> None:
        result = usecases.register_user(args.username, args.password)
        print(
            f"Пользователь '{result['username']}' зарегистрирован "
            f"(id={result['user_id']}). "
            f"Войдите: login --username {result['username']} --password ****"
        )

    def cmd_login(self, args: argparse.Namespace) -> None:
        self.current_user = usecases.login_user(args.username, args.password)
        print(f"Вы вошли как '{self.current_user['username']}'")

    def cmd_show_portfolio(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        summary = usecases.get_portfolio_summary(user["user_id"], args.base)
        base = summary["base"]
        print(f"Портфель пользователя '{summary['username']}' (база: {base}):")
        if not summary["rows"]:
            print("Кошельков пока нет. Пополните USD: buy --currency USD --amount 1000")
            return
        table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {base}"])
        table.align = "r"
        for row in summary["rows"]:
            code = row["currency_code"]
            value = "н/д" if row["value"] is None else format_money(row["value"])
            table.add_row([code, format_amount(code, row["balance"]), value])
        print(table)
        print(f"ИТОГО: {format_money(summary['total'])} {base}")
        if summary["has_unpriced"]:
            print("Внимание: для части валют курс недоступен, они не учтены в итоге.")
        if summary["is_stale"]:
            print(_STALE_HINT)

    def cmd_buy(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        result = usecases.buy(user["user_id"], args.currency, args.amount)
        self._print_trade("Покупка", "Оценочная стоимость покупки", result)

    def cmd_sell(self, args: argparse.Namespace) -> None:
        user = self._require_login()
        result = usecases.sell(user["user_id"], args.currency, args.amount)
        self._print_trade("Продажа", "Оценочная выручка", result)

    @staticmethod
    def _print_trade(title: str, value_title: str, result: dict[str, Any]) -> None:
        code, base = result["currency_code"], result["base"]
        amount = format_amount(code, result["amount"])
        if result["rate"] is None:
            print(f"{title} выполнена: {amount} {code}")
        else:
            rate = format_rate(result["rate"])
            print(f"{title} выполнена: {amount} {code} по курсу {rate} {base}/{code}")
        print("Изменения в портфеле:")
        for change in result["changes"]:
            c = change["currency_code"]
            before = format_amount(c, change["before"])
            after = format_amount(c, change["after"])
            print(f"- {c}: было {before} → стало {after}")
        if result["rate"] is not None:
            print(f"{value_title}: {format_money(result['value'])} {base}")
            if result["is_stale"]:
                print(_STALE_HINT)

    def cmd_get_rate(self, args: argparse.Namespace) -> None:
        info = usecases.get_rate(args.from_code, args.to_code)
        src, dst = info["from"], info["to"]
        print(
            f"Курс {src}→{dst}: {format_rate(info['rate'])} "
            f"(обновлено: {format_timestamp(info['updated_at'])})"
        )
        print(f"Обратный курс {dst}→{src}: {format_rate(info['reverse_rate'])}")
        if info["is_stale"]:
            print(_STALE_HINT)

    def cmd_update_rates(self, args: argparse.Namespace) -> None:
        result = usecases.update_rates(args.source)
        if result.has_errors:
            print("Update completed with errors. Check logs/parser.log for details.")
        else:
            print(
                f"Update successful. Total rates updated: {result.total_rates}. "
                f"Last refresh: {result.last_refresh}"
            )

    def cmd_show_rates(self, args: argparse.Namespace) -> None:
        data = usecases.show_rates(args.currency, args.top, args.base)
        print(f"Rates from cache (updated at {data['last_refresh'] or '—'}):")
        table = PrettyTable(["Пара", "Курс", "Обновлено", "Источник"])
        table.align = "l"
        table.align["Курс"] = "r"
        for row in data["rows"]:
            table.add_row(
                [
                    row["pair"],
                    format_rate(row["rate"]),
                    format_timestamp(row["updated_at"]),
                    row["source"] or "—",
                ]
            )
        print(table)


_STALE_HINT = (
    "Внимание: курс устарел и не удалось его обновить. "
    "Выполните 'update-rates', когда появится сеть."
)


def main() -> None:
    """Точка входа (скрипт ``project``)."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    setup_logging()
    CliApp().run()
