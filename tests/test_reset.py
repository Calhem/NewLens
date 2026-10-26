"""The reset script only acts on the configured database, and only after confirmation."""

import pytest

from newslens.db import read
from scripts import reset_dev


@pytest.fixture
def configured(monkeypatch, settings):
    monkeypatch.setattr(reset_dev, "load_settings", lambda: settings)
    return settings.typedb_database


def test_wrong_confirmation_changes_nothing(configured, db, driver, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "newslens")
    with pytest.raises(SystemExit, match="nothing was changed"):
        reset_dev.main()
    assert driver.databases.contains(db)


def test_confirmed_reset_empties_and_recreates(configured, client, driver, monkeypatch):
    client.post("/api/articles", json={"url": "https://example.org/a"})
    monkeypatch.setattr("builtins.input", lambda prompt: configured)
    reset_dev.main()
    assert read(driver, configured, 'match $a isa article; fetch { "id": $a.doc-id };') == []
    assert read(driver, configured, 'match $m isa methodology; fetch { "v": $m.methodology-version };')
