"""Shared test setup: each test gets its own throwaway newslens-test-* database.

Tests never touch the real `newslens` database and never call any paid API.
"""

import secrets

import pytest
from fastapi.testclient import TestClient

from newslens.api import create_app
from newslens.db import connect
from newslens.migrations import ensure_database
from newslens.settings import load_settings


@pytest.fixture(scope="session")
def base_settings():
    return load_settings()


@pytest.fixture(scope="session")
def driver(base_settings):
    d = connect(base_settings)
    yield d
    d.close()


def _drop(driver, name):
    assert name.startswith("newslens-test-")  # never delete anything else
    if driver.databases.contains(name):
        driver.databases.get(name).delete()


@pytest.fixture
def db_name(driver):
    """A fresh database name; the database itself is created by whoever uses it first."""
    name = f"newslens-test-{secrets.token_hex(4)}"
    yield name
    _drop(driver, name)


@pytest.fixture
def db(driver, db_name):
    """A fresh database with the full schema."""
    ensure_database(driver, db_name)
    return db_name


@pytest.fixture
def settings(base_settings, db_name):
    return base_settings.model_copy(update={"typedb_database": db_name})


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c
