"""The HTTP API: health, submitting a URL, reading it back, and refusing bad input."""

import pytest
from fastapi.testclient import TestClient

from newslens import store
from newslens.api import create_app

URL = "https://news.example.org/2026/10/synthetic-story"


def test_health_reports_database_and_schema(client, settings):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "typedb": "reachable",
                               "database": settings.typedb_database,
                               "schema_version": "000-base", "detail": None}


def test_submit_then_read_back(client):
    created = client.post("/api/articles", json={"url": URL})
    assert created.status_code == 201
    article = created.json()
    assert article["url"] == URL
    assert article["retrieval_status"] == "queued" and article["input_method"] == "url"
    assert article["title"] is None
    [run] = article["runs"]
    assert run["status"] == "queued"
    assert run["methodology_version"] == store.METHODOLOGY_VERSION

    fetched = client.get(f"/api/articles/{article['id']}")
    assert fetched.status_code == 200 and fetched.json() == article
    assert [a["id"] for a in client.get("/api/articles").json()] == [article["id"]]


def test_list_is_newest_first(client):
    ids = [client.post("/api/articles", json={"url": f"{URL}-{i}"}).json()["id"] for i in range(3)]
    assert [a["id"] for a in client.get("/api/articles").json()] == ids[::-1]


def test_text_with_quotes_and_newlines_is_stored_exactly(client):
    url = 'https://example.org/a?q="x"&b=\\y'
    article = client.post("/api/articles", json={"url": url}).json()
    assert client.get(f"/api/articles/{article['id']}").json()["url"] == url


def test_saved_articles_survive_a_restart(settings):
    """A new app with a new database connection sees what the old one saved."""
    with TestClient(create_app(settings)) as first:
        article_id = first.post("/api/articles", json={"url": URL}).json()["id"]
    with TestClient(create_app(settings)) as second:
        assert second.get(f"/api/articles/{article_id}").json()["url"] == URL


@pytest.mark.parametrize("url, reason", [
    ("ftp://example.org/file", "http:// or https://"),
    ("javascript:alert(1)", "http:// or https://"),
    ("example.org/story", "http:// or https://"),
    ("https://localhost/story", "full website name"),
    ("https:///story", "full website name"),
    ("https://user:pass@example.org/", "user name or password"),
    ("https://example.org/a b", "spaces or control characters"),
    ("https://example.org/\x00", "spaces or control characters"),
])
def test_bad_urls_refused_with_a_reason(client, url, reason):
    response = client.post("/api/articles", json={"url": url})
    assert response.status_code == 422
    assert reason in response.text
    assert client.get("/api/articles").json() == []   # nothing was saved


def test_overlong_url_refused(client):
    response = client.post("/api/articles", json={"url": "https://example.org/" + "a" * 2100})
    assert response.status_code == 422


def test_unknown_article_is_404(client):
    assert client.get("/api/articles/" + "0" * 32).status_code == 404


def test_malformed_article_id_is_refused(client):
    assert client.get('/api/articles/x"; match $a isa article;').status_code in (404, 422)
    assert client.get("/api/articles/" + "z" * 32).status_code == 422


def test_missing_methodology_is_detected_not_silently_ignored(db, driver):
    """A match that finds nothing inserts nothing, without an error; submit_url notices."""
    with pytest.raises(store.NotSaved):
        store.submit_url(driver, db, URL)   # ensure_methodology was never called on this db


def test_unreachable_database_gives_503_with_explanation(base_settings):
    settings = base_settings.model_copy(update={"typedb_address": "127.0.0.1:9"})
    with TestClient(create_app(settings)) as c:
        health = c.get("/api/health")
        assert health.status_code == 503
        assert health.json()["typedb"] == "unreachable"
        assert "docker compose ps" in health.json()["detail"]
        assert c.post("/api/articles", json={"url": URL}).status_code == 503
        assert "password" not in health.text
