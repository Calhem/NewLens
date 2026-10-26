"""Delete and recreate the development database: `uv run python -m scripts.reset_dev`.

Only the database named in TYPEDB_DATABASE (.env) is touched, and only after you type its
name to confirm. Everything saved in it is permanently deleted. The schema is loaded again
straight away. To also remove TypeDB's whole data volume, see README "Resetting".
"""

import sys

from newslens import store
from newslens.db import connect
from newslens.migrations import ensure_database
from newslens.settings import ConfigError, load_settings


def main():
    try:
        settings = load_settings()
    except ConfigError as error:
        sys.exit(str(error))
    name = settings.typedb_database
    print(f"This permanently deletes everything in the database '{name}' "
          f"at {settings.typedb_address}.")
    if input(f"Type the database name ({name}) to confirm: ").strip() != name:
        sys.exit("Not confirmed; nothing was changed.")
    driver = connect(settings)
    try:
        if driver.databases.contains(name):
            driver.databases.get(name).delete()
            print(f"Deleted '{name}'.")
        applied = ensure_database(driver, name)
        store.ensure_methodology(driver, name)
        print(f"Recreated '{name}' with schema {', '.join(applied)}.")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
