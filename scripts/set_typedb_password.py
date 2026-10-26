"""Give TypeDB's admin account a strong random password: `uv run python -m scripts.set_typedb_password`.

Steps, in an order that can't lock you out:
1. Generate a random password (32 URL-safe characters, 192 bits of randomness).
2. Write a copy of .env containing it to .env.new (readable only by you).
3. Change the password on the TypeDB server.
4. Replace .env with .env.new.
If step 3 fails, .env.new is deleted and nothing has changed. If step 4 fails, the new
password is in .env.new and the message says so. The password is never printed.

Afterwards, restart the containers that use it: `docker compose up -d --force-recreate api worker`.
Note: `docker compose down -v` deletes TypeDB's data, including this password; run this
script again after recreating the volume.
"""

import os
import re
import secrets
import sys
from pathlib import Path

from pydantic import SecretStr

from newslens.db import connect
from newslens.settings import ConfigError, load_settings

ENV_FILE = Path(".env")


def with_password(env_text, password):
    """The .env text with TYPEDB_PASSWORD set to `password` (added if absent)."""
    line = f"TYPEDB_PASSWORD={password}"
    if re.search(r"^TYPEDB_PASSWORD=.*$", env_text, flags=re.MULTILINE):
        return re.sub(r"^TYPEDB_PASSWORD=.*$", lambda _: line, env_text, flags=re.MULTILINE)
    return env_text.rstrip("\n") + f"\n{line}\n"


def change_password(settings, env_file=ENV_FILE):
    """Set a new random password for settings.typedb_username, on the server and in env_file."""
    password = secrets.token_urlsafe(24)
    staged = env_file.with_name(env_file.name + ".new")
    staged.write_text(with_password(env_file.read_text(), password))
    os.chmod(staged, 0o600)
    try:
        driver = connect(settings)
        try:
            driver.users.get(settings.typedb_username).update_password(password)
        finally:
            driver.close()
    except Exception:
        staged.unlink()
        raise
    try:
        staged.replace(env_file)
    except OSError as error:
        raise RuntimeError(f"The password was changed on the server, but {env_file} could not be "
                           f"replaced ({error}). The new password is in {staged}.") from None
    return settings.model_copy(update={"typedb_password": SecretStr(password)})


def main():
    if not ENV_FILE.exists():
        sys.exit("No .env file here. Run this from the project folder after `cp .env.example .env`.")
    try:
        settings = load_settings()
    except ConfigError as error:
        sys.exit(str(error))
    change_password(settings)
    print(f"Changed the TypeDB password for '{settings.typedb_username}' and saved it in .env "
          "(not shown).\nRestart the app so it uses it: docker compose up -d --force-recreate api worker")


if __name__ == "__main__":
    main()
