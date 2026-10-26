"""NewsLens settings, read from environment variables (and a local .env file, if present).

Every setting is checked when it is loaded. A missing or malformed value stops the program
with a message that names the setting and says how to fix it, instead of failing later with
a confusing error. Secret values are kept as SecretStr, so they never appear in logs.
"""

import re

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADDRESS = re.compile(r"^[A-Za-z0-9.\-]+:\d{1,5}$")


class ConfigError(Exception):
    """The configuration is missing or invalid. The message says what to change."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    typedb_address: str = Field(description="host:port of the TypeDB server, e.g. 127.0.0.1:1731")
    typedb_username: str = Field(min_length=1)
    typedb_password: SecretStr
    typedb_database: str = Field(description="database name: lowercase letters, digits, hyphens")

    @field_validator("typedb_address")
    @classmethod
    def _address(cls, value):
        if not _ADDRESS.match(value) or not 0 < int(value.rsplit(":", 1)[1]) < 65536:
            raise ValueError("must look like host:port, for example 127.0.0.1:1731")
        return value

    @field_validator("typedb_database")
    @classmethod
    def _database(cls, value):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
            raise ValueError("must be lowercase letters, digits and hyphens, for example newslens")
        return value

    @field_validator("typedb_password")
    @classmethod
    def _password(cls, value):
        if not value.get_secret_value():
            raise ValueError("must not be empty")
        return value


def load_settings(**overrides):
    """Load and check the settings, or raise ConfigError with a plain-English explanation."""
    try:
        return Settings(**overrides)
    except ValidationError as error:
        problems = []
        for item in error.errors():
            name = str(item["loc"][0]).upper() if item["loc"] else "settings"
            reason = "is missing" if item["type"] == "missing" else item["msg"].removeprefix("Value error, ")
            problems.append(f"  - {name} {reason}")
        raise ConfigError(
            "NewsLens configuration problem:\n" + "\n".join(problems)
            + "\nSet these in your .env file (copy .env.example to start) or as environment variables."
        ) from None
