"""Планировщик периодического обновления курсов.

Запуск отдельно от CLI::

    uv run python -m valutatrade_hub.parser_service.scheduler --interval 300
"""

import argparse
import logging
import time

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import PARSER_LOGGER, setup_logging
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater, build_updater


class RatesScheduler:
    """Запускает RatesUpdater.run_update() каждые ``interval_seconds`` секунд."""

    def __init__(self, updater: RatesUpdater, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("Интервал должен быть положительным числом секунд")
        self.updater = updater
        self.interval_seconds = interval_seconds
        self.logger = logging.getLogger(PARSER_LOGGER)

    def run(self, iterations: int | None = None) -> int:
        """Крутить цикл обновлений; вернуть число выполненных запусков.

        Args:
            iterations: сколько раз обновить (None — бесконечно, до Ctrl+C).
        """
        done = 0
        try:
            while iterations is None or done < iterations:
                try:
                    self.updater.run_update()
                except ApiRequestError as error:
                    self.logger.error(f"Scheduled update failed: {error.reason}")
                done += 1
                if iterations is not None and done >= iterations:
                    break
                self.logger.info(f"Next update in {self.interval_seconds} s...")
                time.sleep(self.interval_seconds)
        except KeyboardInterrupt:
            self.logger.info("Scheduler stopped by user.")
        return done


def main() -> None:
    """CLI планировщика."""
    defaults = ParserConfig()
    parser = argparse.ArgumentParser(description="Периодическое обновление курсов")
    parser.add_argument(
        "--interval", type=int, default=defaults.UPDATE_INTERVAL_SECONDS
    )
    args = parser.parse_args()
    setup_logging()
    RatesScheduler(build_updater(), args.interval).run()


if __name__ == "__main__":
    main()
