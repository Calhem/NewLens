"""Set the AI model spending limit: `uv run python -m scripts.set_budget --limit 5 --warning 4`.

Amounts are US dollars. The limit lives in TypeDB, so every process sees the same one and a
restart can't reset it. Until a limit is set, every model call is refused. Run with no
arguments to see the current budget and spend.
"""

import argparse
import sys

from newslens.db import connect
from newslens.llm import Budget, set_budget_limit
from newslens.migrations import ensure_database
from newslens.settings import ConfigError, load_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", help="total spending limit in US dollars")
    parser.add_argument("--warning", help="warning level in US dollars (defaults to the limit)")
    args = parser.parse_args()
    try:
        settings = load_settings()
    except ConfigError as error:
        sys.exit(str(error))
    driver = connect(settings)
    try:
        ensure_database(driver, settings.typedb_database)
        if args.limit is not None:
            set_budget_limit(driver, settings.typedb_database, args.limit, args.warning)
        summary = Budget(driver, settings.typedb_database).summary()
    finally:
        driver.close()
    limit = summary["limit_usd"]
    print(f"Limit: {'not set (every model call is refused)' if limit is None else f'${limit:.2f}'}")
    print(f"Spent or reserved: ${summary['committed_usd']:.4f} in {len(summary['calls'])} call(s)")
    if summary["held"]:
        print(f"{len(summary['held'])} call(s) held as possibly charged: check the Anthropic Console.")


if __name__ == "__main__":
    main()
