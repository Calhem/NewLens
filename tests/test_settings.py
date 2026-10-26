"""Configuration is checked at startup and problems are explained in plain words."""

import pytest

from newslens.settings import ConfigError, load_settings

GOOD = dict(typedb_address="127.0.0.1:1731", typedb_username="admin",
            typedb_password="password", typedb_database="newslens")


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    for name in ("TYPEDB_ADDRESS", "TYPEDB_USERNAME", "TYPEDB_PASSWORD", "TYPEDB_DATABASE",
                 "NEWSLENS_ENVIRONMENT", "NEWSLENS_MODEL_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def load(**changes):
    return load_settings(_env_file=None, **{**GOOD, **changes})


def test_good_settings_load():
    assert load().typedb_database == "newslens"


def test_missing_settings_are_all_named():
    with pytest.raises(ConfigError) as error:
        load_settings(_env_file=None)
    message = str(error.value)
    for name in ("TYPEDB_ADDRESS", "TYPEDB_USERNAME", "TYPEDB_PASSWORD", "TYPEDB_DATABASE"):
        assert f"{name} is missing" in message
    assert ".env.example" in message


@pytest.mark.parametrize("address", ["localhost", "127.0.0.1:", "127.0.0.1:99999", "http://x:1"])
def test_malformed_address(address):
    with pytest.raises(ConfigError, match="TYPEDB_ADDRESS must look like host:port"):
        load(typedb_address=address)


@pytest.mark.parametrize("name", ["NewsLens", "news lens", "-x", ""])
def test_malformed_database_name(name):
    with pytest.raises(ConfigError, match="TYPEDB_DATABASE"):
        load(typedb_database=name)


def test_empty_password_refused():
    with pytest.raises(ConfigError, match="TYPEDB_PASSWORD must not be empty"):
        load(typedb_password="")


def test_password_never_shown():
    settings = load(typedb_password="s3cret-value")
    assert "s3cret-value" not in repr(settings) and "s3cret-value" not in str(settings)


def test_environment_variables_are_used(monkeypatch):
    for key, value in GOOD.items():
        monkeypatch.setenv(key.upper(), value)
    monkeypatch.setenv("TYPEDB_DATABASE", "from-env")
    assert load_settings(_env_file=None).typedb_database == "from-env"


def test_model_provider_defaults_to_none():
    assert load().newslens_model_provider == "none"


def test_anthropic_provider_needs_a_key():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY is required"):
        load(newslens_model_provider="anthropic")
    settings = load(newslens_model_provider="anthropic", anthropic_api_key="sk-test-not-real")  # pragma: allowlist secret
    assert "sk-test-not-real" not in repr(settings)
