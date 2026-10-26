"""NewsLens settings, read from environment variables (and a local .env file, if present).

Every setting is checked when it is loaded. A missing or malformed value stops the program
with a message that names the setting and says how to fix it, instead of failing later with
a confusing error. Secret values are kept as SecretStr, so they never appear in logs.
"""

import re
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ADDRESS = re.compile(r"^[A-Za-z0-9.\-]+:\d{1,5}$")

# TypeDB CE's built-in password for `admin`. Acceptable only on a single computer, with
# TypeDB reachable from that computer alone (as compose.yaml sets up).
DEFAULT_TYPEDB_PASSWORD = "password"
MIN_PRODUCTION_PASSWORD = 16


class ConfigError(Exception):
    """The configuration is missing or invalid. The message says what to change."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    typedb_address: str = Field(description="host:port of the TypeDB server, e.g. 127.0.0.1:1731")
    typedb_username: str = Field(min_length=1)
    typedb_password: SecretStr
    typedb_database: str = Field(description="database name: lowercase letters, digits, hyphens")
    # "development": one computer, everything bound to 127.0.0.1. Anything shared with other
    # people or computers is "production", which refuses insecure defaults.
    newslens_environment: Literal["development", "production"] = "development"
    # Which AI model provider extracts claims. "none" (the default) never calls a model, so
    # nothing can cost money until the owner chooses a provider, adds a key and sets a budget.
    newslens_model_provider: Literal["none", "anthropic"] = "none"
    anthropic_api_key: SecretStr | None = None
    # Where the fetcher keeps its per-website rate-limit lock files.
    fetch_lock_dir: str = "data/host-locks"

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

    @model_validator(mode="after")
    def _provider_key(self):
        if self.newslens_model_provider == "anthropic" and not (
                self.anthropic_api_key and self.anthropic_api_key.get_secret_value()):
            raise ValueError("ANTHROPIC_API_KEY is required when NEWSLENS_MODEL_PROVIDER is anthropic")
        return self

    @model_validator(mode="after")
    def _production_safety(self):
        if self.newslens_environment == "production":
            password = self.typedb_password.get_secret_value()
            if password == DEFAULT_TYPEDB_PASSWORD or len(password) < MIN_PRODUCTION_PASSWORD:
                raise ValueError(
                    f"TYPEDB_PASSWORD must be changed from TypeDB's default and be at least "
                    f"{MIN_PRODUCTION_PASSWORD} characters when NEWSLENS_ENVIRONMENT is production "
                    f"(run: uv run python -m scripts.set_typedb_password)")
        return self

    @property
    def uses_default_password(self):
        return self.typedb_password.get_secret_value() == DEFAULT_TYPEDB_PASSWORD


def load_settings(**overrides):
    """Load and check the settings, or raise ConfigError with a plain-English explanation."""
    try:
        return Settings(**overrides)
    except ValidationError as error:
        problems = []
        for item in error.errors():
            reason = "is missing" if item["type"] == "missing" else item["msg"].removeprefix("Value error, ")
            # Checks across several settings name the settings in their own message.
            problems.append(f"  - {str(item['loc'][0]).upper()} {reason}" if item["loc"] else f"  - {reason}")
        raise ConfigError(
            "NewsLens configuration problem:\n" + "\n".join(problems)
            + "\nSet these in your .env file (copy .env.example to start) or as environment variables."
        ) from None
