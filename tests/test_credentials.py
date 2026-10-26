"""Credential safety: no insecure defaults outside development, and password rotation."""

import secrets

import pytest
from pydantic import SecretStr

from newslens.db import connect
from newslens.settings import ConfigError, load_settings
from scripts.set_typedb_password import change_password, with_password

GOOD = dict(typedb_address="127.0.0.1:1731", typedb_username="admin",
            typedb_password="password", typedb_database="newslens")


def load(**changes):
    return load_settings(_env_file=None, **{**GOOD, **changes})


def test_default_password_allowed_in_development():
    assert load().uses_default_password


@pytest.mark.parametrize("password", ["password", "short-but-new"])
def test_production_refuses_default_or_short_password(password):
    with pytest.raises(ConfigError, match="TYPEDB_PASSWORD must be changed"):
        load(newslens_environment="production", typedb_password=password)


def test_production_accepts_strong_password():
    assert load(newslens_environment="production", typedb_password="x" * 32)


def test_unknown_environment_refused():
    with pytest.raises(ConfigError, match="NEWSLENS_ENVIRONMENT"):
        load(newslens_environment="staging")


def test_env_text_rewrite_keeps_other_lines():
    text = "A=1\nTYPEDB_PASSWORD=password\nB=2\n"
    assert with_password(text, "new\\1") == "A=1\nTYPEDB_PASSWORD=new\\1\nB=2\n"
    assert with_password("A=1", "p") == "A=1\nTYPEDB_PASSWORD=p\n"


@pytest.fixture
def temporary_user(driver, base_settings):
    """A throwaway TypeDB user, so the test never changes the real admin password."""
    name, password = f"newslens-test-{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    driver.users.create(name, password)
    yield base_settings.model_copy(update={"typedb_username": name,
                                           "typedb_password": SecretStr(password)})
    if driver.users.contains(name):
        driver.users.get(name).delete()


def test_change_password_updates_server_and_env_file(temporary_user, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"KEEP=me\nTYPEDB_PASSWORD={temporary_user.typedb_password.get_secret_value()}\n")
    new_settings = change_password(temporary_user, env_file)
    new_password = new_settings.typedb_password.get_secret_value()
    assert len(new_password) >= 32 and new_password != temporary_user.typedb_password.get_secret_value()
    assert env_file.read_text() == f"KEEP=me\nTYPEDB_PASSWORD={new_password}\n"
    assert oct(env_file.stat().st_mode)[-3:] == "600"
    connect(new_settings).close()                       # the new password works
    with pytest.raises(Exception, match="CXN16"):
        connect(temporary_user)                         # the old one doesn't


def test_failed_server_change_leaves_env_untouched(base_settings, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("TYPEDB_PASSWORD=password\n")
    wrong = base_settings.model_copy(update={"typedb_password": SecretStr("wrong-password")})
    with pytest.raises(Exception):
        change_password(wrong, env_file)
    assert env_file.read_text() == "TYPEDB_PASSWORD=password\n"
    assert not (tmp_path / ".env.new").exists()
